from __future__ import annotations

import math

import pytest
from inspect_ai.scorer import CORRECT, INCORRECT

from inspect_eval_probes.compare import (
    MetricChange,
    VerdictChange,
    compare_metric,
    compare_verdict,
    compare_verdicts,
    divergent_metrics,
    in_negative_class,
    is_scalar,
)
from inspect_eval_probes.contract import Relation, Tolerance

NAN = float("nan")


class TestIsScalar:
    @pytest.mark.parametrize("value", [0, 1, -3, 0.5, NAN, True, False])
    def test_scalars(self, value):
        assert is_scalar(value)

    @pytest.mark.parametrize("value", ["1.0", {"a": 1}, [1, 2], None, (1,)])
    def test_non_scalars(self, value):
        assert not is_scalar(value)


class TestCompareMetric:
    def test_unchanged(self):
        assert compare_metric("m", 1.0, 1.0).change is MetricChange.UNCHANGED

    def test_value_moved(self):
        c = compare_metric("m", 1.0, 0.0)
        assert c.change is MetricChange.VALUE_MOVED
        assert c.is_violation

    def test_became_nan(self):
        c = compare_metric("m", 1.0, NAN)
        assert c.change is MetricChange.BECAME_NAN
        assert c.is_violation

    def test_left_nan(self):
        # a transformation that RESCUES a NaN violates the contract too
        c = compare_metric("m", NAN, 1.0)
        assert c.change is MetricChange.LEFT_NAN
        assert c.is_violation

    def test_nan_to_nan_is_unchanged_not_a_change(self):
        # the trap: a bare != would call this a change, since nan != nan
        c = compare_metric("m", NAN, NAN)
        assert c.change is MetricChange.UNCHANGED
        assert not c.is_violation

    def test_non_scalar_is_not_comparable_not_unchanged(self):
        c = compare_metric("m", {"a": 1}, {"a": 2})
        assert c.change is MetricChange.NOT_COMPARABLE
        assert not c.is_violation

    def test_non_scalar_identical_still_not_comparable(self):
        # an unprobed metric must be visible, never silently treated as unchanged
        c = compare_metric("m", {"a": 1}, {"a": 1})
        assert c.change is MetricChange.NOT_COMPARABLE

    def test_tolerance_absorbs_a_small_move(self):
        c = compare_metric("m", 1.0, 1.01, Tolerance(absolute=0.05))
        assert c.change is MetricChange.UNCHANGED

    def test_tolerance_does_not_absorb_a_large_move(self):
        c = compare_metric("m", 1.0, 1.5, Tolerance(absolute=0.05))
        assert c.change is MetricChange.VALUE_MOVED

    def test_tolerance_cannot_absorb_became_nan(self):
        # no amount of slack makes "the samples vanished" acceptable
        c = compare_metric("m", 1.0, NAN, Tolerance(absolute=1e9, relative=1e9))
        assert c.change is MetricChange.BECAME_NAN

    def test_the_worldsense_signature(self):
        # this is the real observed pair, verified end to end through inspect_ai.eval
        assert compare_metric("accuracy", 1.0, 1.0).change is MetricChange.UNCHANGED
        assert compare_metric("ws_accuracy", 1.0, 0.0).change is MetricChange.VALUE_MOVED


class TestNegativeClass:
    def test_inspect_string_verdicts(self):
        assert in_negative_class(INCORRECT) is True
        assert in_negative_class(CORRECT) is False

    def test_numeric_endpoints(self):
        assert in_negative_class(0) is True
        assert in_negative_class(0.0) is True
        assert in_negative_class(1) is False
        assert in_negative_class(1.0) is False

    def test_partial_credit_is_undecidable_not_guessed(self):
        # picking a threshold would put an unstated judgment inside the tool
        assert in_negative_class(0.5) is None
        assert in_negative_class(0.99) is None

    def test_booleans(self):
        assert in_negative_class(False) is True
        assert in_negative_class(True) is False

    def test_dicts_and_nan_undecidable(self):
        assert in_negative_class({"a": 1}) is None
        assert in_negative_class(NAN) is None
        assert in_negative_class(None) is None


class TestCompareVerdictEqual:
    def test_unchanged(self):
        c = compare_verdict(Relation.EQUAL, 0, CORRECT, CORRECT)
        assert c.change is VerdictChange.UNCHANGED

    def test_changed_either_direction(self):
        assert compare_verdict(Relation.EQUAL, 0, CORRECT, INCORRECT).is_violation
        assert compare_verdict(Relation.EQUAL, 0, INCORRECT, CORRECT).is_violation


class TestCompareVerdictStaysIncorrect:
    def test_wrong_stays_wrong_passes(self):
        c = compare_verdict(Relation.STAYS_INCORRECT, 0, INCORRECT, INCORRECT)
        assert c.change is VerdictChange.UNCHANGED

    def test_wrong_becomes_right_is_the_violation(self):
        c = compare_verdict(Relation.STAYS_INCORRECT, 0, INCORRECT, CORRECT)
        assert c.change is VerdictChange.LEFT_NEGATIVE_CLASS
        assert c.is_violation

    def test_correct_baseline_is_not_evidence_either_way(self):
        # nothing to preserve if the baseline was already right
        c = compare_verdict(Relation.STAYS_INCORRECT, 0, CORRECT, CORRECT)
        assert c.change is VerdictChange.NOT_COMPARABLE
        assert not c.is_violation

    def test_undecidable_baseline_is_not_comparable(self):
        c = compare_verdict(Relation.STAYS_INCORRECT, 0, 0.5, 0.5)
        assert c.change is VerdictChange.NOT_COMPARABLE

    def test_undecidable_after_is_not_comparable(self):
        c = compare_verdict(Relation.STAYS_INCORRECT, 0, INCORRECT, 0.5)
        assert c.change is VerdictChange.NOT_COMPARABLE


class TestCompareVerdicts:
    def test_pairs_up_by_index(self):
        out = compare_verdicts(Relation.EQUAL, [CORRECT, INCORRECT], [CORRECT, CORRECT])
        assert [c.change for c in out] == [VerdictChange.UNCHANGED, VerdictChange.CHANGED]
        assert out[1].case_index == 1

    def test_length_mismatch_is_an_error_not_a_verdict(self):
        with pytest.raises(ValueError, match="case count must be preserved"):
            compare_verdicts(Relation.EQUAL, [CORRECT], [CORRECT, CORRECT])


class TestDivergentMetrics:
    def _cmp(self, pairs):
        return [compare_metric(n, b, a) for n, b, a in pairs]

    def test_some_but_not_all_moved(self):
        # the worldsense signature
        assert divergent_metrics(
            self._cmp([("accuracy", 1.0, 1.0), ("ws_accuracy", 1.0, 0.0)])
        )

    def test_all_moved_is_not_divergence(self):
        assert not divergent_metrics(self._cmp([("a", 1.0, 0.0), ("b", 1.0, 0.0)]))

    def test_none_moved_is_not_divergence(self):
        assert not divergent_metrics(self._cmp([("a", 1.0, 1.0), ("b", 1.0, 1.0)]))

    def test_single_metric_cannot_diverge(self):
        assert not divergent_metrics(self._cmp([("a", 1.0, 0.0)]))

    def test_non_comparable_metrics_are_excluded_from_the_judgement(self):
        cmps = self._cmp([("a", 1.0, 1.0), ("b", 1.0, 0.0), ("c", {"x": 1}, {"x": 2})])
        assert divergent_metrics(cmps)


def test_nan_comparison_never_uses_bare_inequality():
    # guards the specific trap: `!=` reports an already-NaN baseline as changed
    assert NAN != NAN  # noqa: PLR0124 - asserting the trap itself, deliberately
    assert compare_metric("m", NAN, NAN).change is MetricChange.UNCHANGED
    assert not math.isnan(0.0)
