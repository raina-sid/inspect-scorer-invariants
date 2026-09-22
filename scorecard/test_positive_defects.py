"""Arm 1 of the scorecard: three real scoring defects that MUST be reported as FAIL.

Real means the verdict or a metric genuinely moves, which is all this arm tests. It does NOT mean all
three are bugs in inspect_evals -- two of them reproduce their upstream reference implementations
verbatim, so only worldsense is the port's own. See fixtures.PROVENANCE and
validation/provenance-audit.md. That distinction does not affect these tests: a detector must flag the
mechanism regardless of which repository is responsible for it.

These are the defects the pre-registered run found, on three different scorer types. If any of
these stops failing, either the probe regressed or the fixture stopped reproducing the mechanism --
either way the package's central claim is no longer supported and the suite must go red.

Not a recall estimate. These defects were FOUND by these probes, so detecting them is circular by
construction. What this arm establishes is that the mechanism is still reproduced end to end.
"""

from __future__ import annotations

import math

from inspect_ai.scorer import accuracy

from inspect_scorer_probes import Contract, Outcome, probe
from inspect_scorer_probes.invariants import CUE_CASE, MARKUP, WRONG_STAYS_INCORRECT

from .fixtures import (
    NOVELTY_CASES,
    PROVENANCE,
    TAU2_CASES,
    WORLDSENSE_CASES,
    bold_one_generation,
    communicated_info_reduction,
    differently_wrong_error_code,
    novelty_scorer_reduction,
    worldsense_scorer_reduction,
    ws_accuracy_reduction,
)


def _only(report, invariant, transformation):
    for r in report.results:
        if r.invariant == invariant and r.transformation == transformation:
            return r
    raise AssertionError(f"no result for {invariant}/{transformation}:\n{report.render()}")


class TestWorldsenseMetricLayer:
    """The defect is in the METRIC, not the scorer. Verdicts are byte-identical."""

    def _report(self):
        return probe(
            worldsense_scorer_reduction(),
            {"accuracy": accuracy(), "ws_accuracy": ws_accuracy_reduction()},
            WORLDSENSE_CASES,
            Contract(invariants=(CUE_CASE,)),
            scorer_source="worldsense_scorer_reduction()",
        )

    def test_fails(self):
        assert _only(self._report(), "CUE_CASE", "cue_case_flip").outcome is Outcome.FAIL

    def test_fails_at_the_metric_layer_only(self):
        r = _only(self._report(), "CUE_CASE", "cue_case_flip")
        assert r.layers == ("metric",)
        assert all(not v.is_violation for v in r.verdicts), "the scorer must be clean"

    def test_reproduces_the_observed_numbers(self):
        r = _only(self._report(), "CUE_CASE", "cue_case_flip")
        by_name = {m.name: (m.before, m.after) for m in r.metrics}
        assert by_name["accuracy"] == (1.0, 1.0)
        assert by_name["ws_accuracy"] == (1.0, 0.0)

    def test_reports_divergent_metrics(self):
        # the only thing separating a silent 1.0 -> 0.0 from a legitimate score of zero
        r = _only(self._report(), "CUE_CASE", "cue_case_flip")
        assert any("DIVERGENT_METRICS" in d for d in r.details)

    def test_the_metric_launders_nan_into_zero_not_nan(self):
        # NaN would announce itself; 0.0 does not. Pin the laundering so a future "fix" that
        # returns NaN instead cannot silently change what this fixture demonstrates.
        r = _only(self._report(), "CUE_CASE", "cue_case_flip")
        after = {m.name: m.after for m in r.metrics}["ws_accuracy"]
        assert after == 0.0
        assert not math.isnan(after), "must be 0.0, not NaN -- NaN would announce itself"

    def test_reproduction_carries_every_case(self):
        # a metric-layer finding cannot be reproduced from a single case
        repro = self._report().failures[0].reproduction
        assert repro is not None
        assert len(repro.baseline_cases) == len(WORLDSENSE_CASES)
        assert repro.code is not None and "worldsense_scorer_reduction()" in repro.code


class TestNoveltyBenchMarkup:
    """Markup splits an equivalence class: distinct_k 1 -> 2 for identical content."""

    def _report(self):
        return probe(
            novelty_scorer_reduction(),
            [accuracy()],
            NOVELTY_CASES,
            Contract(invariants=(MARKUP,)),
            transforms=[bold_one_generation()],
        )

    def test_fails(self):
        assert _only(self._report(), "MARKUP", "bold_one_generation").outcome is Outcome.FAIL

    def test_fails_at_the_scorer_layer(self):
        r = _only(self._report(), "MARKUP", "bold_one_generation")
        assert "scorer" in r.layers

    def test_distinct_k_goes_from_one_to_two(self):
        r = _only(self._report(), "MARKUP", "bold_one_generation")
        moved = [v for v in r.verdicts if v.is_violation]
        assert len(moved) == 1
        assert (moved[0].before, moved[0].after) == (1, 2)

    def test_the_transformation_mutates_metadata_not_the_completion(self):
        # this eval keeps its k generations in metadata["all_completions"]
        t = bold_one_generation()
        assert t.mutates == {"metadata"}
        after = t.apply(NOVELTY_CASES[0])
        assert after is not None
        assert after.completion == NOVELTY_CASES[0].completion
        assert after.metadata["all_completions"][0] == "**Amelia**"


class TestTau2UnanchoredSubstring:
    """A differently-wrong answer becomes CORRECT because it contains '4' as a substring."""

    def _report(self):
        return probe(
            communicated_info_reduction(),
            [accuracy()],
            TAU2_CASES,
            Contract(invariants=(WRONG_STAYS_INCORRECT,)),
            transforms=[differently_wrong_error_code()],
        )

    def test_fails(self):
        r = _only(self._report(), "WRONG_STAYS_INCORRECT", "differently_wrong_error_code")
        assert r.outcome is Outcome.FAIL

    def test_a_wrong_answer_left_the_negative_class(self):
        r = _only(self._report(), "WRONG_STAYS_INCORRECT", "differently_wrong_error_code")
        moved = [v for v in r.verdicts if v.is_violation]
        assert len(moved) == 1
        assert moved[0].change.value == "left_negative_class"

    def test_both_completions_are_genuinely_wrong(self):
        # the point of the finding: neither answer communicates the value 4
        before = TAU2_CASES[0].completion
        after = differently_wrong_error_code().apply(TAU2_CASES[0])
        assert after is not None
        assert "4" not in before
        assert "404" in after.completion
        assert "the value is 4" not in after.completion.lower()


class TestArmSummary:
    def test_all_three_defects_fail_and_they_are_three_different_scorer_types(self):
        reports = {
            "worldsense": probe(
                worldsense_scorer_reduction(),
                {"accuracy": accuracy(), "ws_accuracy": ws_accuracy_reduction()},
                WORLDSENSE_CASES,
                Contract(invariants=(CUE_CASE,)),
            ),
            "novelty_bench": probe(
                novelty_scorer_reduction(),
                [accuracy()],
                NOVELTY_CASES,
                Contract(invariants=(MARKUP,)),
                transforms=[bold_one_generation()],
            ),
            "tau2": probe(
                communicated_info_reduction(),
                [accuracy()],
                TAU2_CASES,
                Contract(invariants=(WRONG_STAYS_INCORRECT,)),
                transforms=[differently_wrong_error_code()],
            ),
        }
        for name, report in reports.items():
            assert report.failures, f"{name} must FAIL:\n{report.render()}"

        # three distinct layers/relations, not three instances of one thing
        layers = {n: reports[n].failures[0].layers for n in reports}
        assert layers["worldsense"] == ("metric",)
        assert "scorer" in layers["novelty_bench"]
        assert "scorer" in layers["tau2"]

    def test_every_fixture_has_provenance(self):
        for name in ("worldsense", "novelty_bench", "tau2"):
            entry = PROVENANCE[name]
            assert entry["source"], name
            assert entry["observed"], name
            assert entry["how"], name
