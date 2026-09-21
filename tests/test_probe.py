"""End-to-end tests of probe() and assert_invariants()."""

from __future__ import annotations

import asyncio
import itertools

import pytest
from inspect_ai.scorer import (
    CORRECT,
    INCORRECT,
    SampleScore,
    Score,
    accuracy,
    metric,
    scorer,
)

from scorer_invariants import (
    Case,
    Contract,
    InvariantViolation,
    Outcome,
    Tolerance,
    assert_invariants,
    probe,
    probe_async,
    transform,
)
from scorer_invariants.compare import MetricChange
from scorer_invariants.invariants import (
    CODE_FORMATTING,
    CUE_CASE,
    CUE_WHITESPACE,
    MARKUP,
    WRONG_STAYS_INCORRECT,
)
from scorer_invariants.pipeline import observe, observe_async, resolve_metrics

CASES = [
    Case(completion="ANSWER: TRUE", target="TRUE"),
    Case(completion="ANSWER: FALSE", target="FALSE"),
]


def _answer_of(completion: str) -> str:
    return completion.split(":")[-1].strip()


@scorer(metrics=[accuracy()])
def case_insensitive_scorer():
    """Accepts any case, and records the raw token as Score.answer -- as worldsense does."""

    async def score(state, target):
        answer = _answer_of(state.output.completion)
        return Score(
            value=CORRECT if answer.upper() == target.text.upper() else INCORRECT,
            answer=answer,
        )

    return score


@scorer(metrics=[accuracy()])
def case_sensitive_scorer():
    async def score(state, target):
        answer = _answer_of(state.output.completion)
        return Score(value=CORRECT if answer == target.text else INCORRECT, answer=answer)

    return score


@metric
def upper_keyed_accuracy():
    """A weighted accuracy whose weight table is keyed on UPPERCASE answers only.

    This is worldsense's defect in miniature, including the laundering: when no answer can be
    keyed, the weight total is 0 and the guard returns 0.0 rather than NaN -- so the output is
    indistinguishable from a model that got everything wrong.
    """
    weights = {"TRUE": 0.5, "FALSE": 0.5}

    def compute(scores: list[SampleScore]) -> float:
        keyed = [weights.get(s.score.answer or "") for s in scores]
        total = sum(w for w in keyed if w is not None)
        if total == 0:
            return 0.0
        earned = sum(
            w for w, s in zip(keyed, scores) if w is not None and s.score.value == CORRECT
        )
        return earned / total

    return compute


@scorer(metrics=[accuracy()])
def raising_scorer():
    async def score(state, target):
        raise RuntimeError("scorer exploded")

    return score


@scorer(metrics=[accuracy()])
def none_scorer():
    async def score(state, target):
        return None

    return score


@scorer(metrics=[accuracy()])
def flaky_scorer():
    counter = itertools.count()

    async def score(state, target):
        run = next(counter) // len(CASES)
        return Score(value=CORRECT if run % 2 == 0 else INCORRECT)

    return score


def _result(report, invariant, transformation):
    for r in report.results:
        if r.invariant == invariant and r.transformation == transformation:
            return r
    raise AssertionError(f"no result for {invariant}/{transformation}")


class TestCleanScorer:
    def test_case_insensitive_scorer_passes_cue_case(self):
        report = probe(
            case_insensitive_scorer(),
            [accuracy()],
            CASES,
            Contract(invariants=(CUE_CASE,)),
        )
        assert _result(report, "CUE_CASE", "cue_case_flip").outcome is Outcome.PASS
        assert report.failures == ()
        assert_invariants(report)  # must not raise


class TestScorerLayerFailure:
    def test_case_sensitive_scorer_fails_at_the_scorer_layer(self):
        report = probe(
            case_sensitive_scorer(),
            [accuracy()],
            CASES,
            Contract(invariants=(CUE_CASE,)),
        )
        r = _result(report, "CUE_CASE", "cue_case_flip")
        assert r.outcome is Outcome.FAIL
        assert r.layers == ("scorer", "metric")  # accuracy moves too, since verdicts moved
        assert "scorer" in r.layers
        assert r.label.startswith("FAIL [")

    def test_assert_invariants_raises_and_includes_the_grid(self):
        report = probe(
            case_sensitive_scorer(), [accuracy()], CASES, Contract(invariants=(CUE_CASE,))
        )
        with pytest.raises(InvariantViolation, match="declared invariant"):
            assert_invariants(report)


class TestMetricLayerFailure:
    """The worldsense shape: verdicts identical, aggregate moves."""

    def test_verdicts_hold_while_the_weighted_metric_collapses(self):
        report = probe(
            case_insensitive_scorer(),
            {"accuracy": accuracy(), "weighted": upper_keyed_accuracy()},
            CASES,
            Contract(invariants=(CUE_CASE,)),
        )
        r = _result(report, "CUE_CASE", "cue_case_flip")
        assert r.outcome is Outcome.FAIL
        assert r.layers == ("metric",), "the scorer layer must be clean"
        assert all(not v.is_violation for v in r.verdicts)

        by_name = {m.name: m for m in r.metrics}
        assert not by_name["accuracy"].is_violation
        assert by_name["weighted"].is_violation
        assert (by_name["weighted"].before, by_name["weighted"].after) == (1.0, 0.0)

    def test_divergent_metrics_is_reported(self):
        report = probe(
            case_insensitive_scorer(),
            {"accuracy": accuracy(), "weighted": upper_keyed_accuracy()},
            CASES,
            Contract(invariants=(CUE_CASE,)),
        )
        r = _result(report, "CUE_CASE", "cue_case_flip")
        assert any("DIVERGENT_METRICS" in d for d in r.details)

    def test_a_single_metric_would_have_hidden_it_from_divergence_but_not_from_failure(self):
        report = probe(
            case_insensitive_scorer(),
            {"weighted": upper_keyed_accuracy()},
            CASES,
            Contract(invariants=(CUE_CASE,)),
        )
        r = _result(report, "CUE_CASE", "cue_case_flip")
        assert r.outcome is Outcome.FAIL
        assert not any("DIVERGENT_METRICS" in d for d in r.details)


class TestExclusions:
    def test_excluded_invariant_is_reported_not_probed(self):
        report = probe(
            case_sensitive_scorer(),
            [accuracy()],
            CASES,
            Contract(invariants=(CUE_WHITESPACE,), exclusions=(CUE_CASE,)),
        )
        r = _result(report, "CUE_CASE", "-")
        assert r.outcome is Outcome.EXCLUDED
        assert not r.executed

    def test_excluding_the_failing_invariant_removes_the_failure_but_changes_the_hash(self):
        asserted = Contract(invariants=(CUE_CASE,))
        silenced = Contract(invariants=(CUE_WHITESPACE,), exclusions=(CUE_CASE,))
        a = probe(case_sensitive_scorer(), [accuracy()], CASES, asserted)
        b = probe(case_sensitive_scorer(), [accuracy()], CASES, silenced)
        assert a.failures and not b.failures
        assert a.contract_hash != b.contract_hash


class TestNonRepeatable:
    def test_flaky_scorer_yields_one_error_and_no_failures(self):
        report = probe(
            flaky_scorer(), [accuracy()], CASES, Contract(invariants=(CUE_CASE,))
        )
        assert len(report.errors) == 1
        assert report.failures == ()
        assert "NONREPEATABLE_BASELINE" in report.errors[0].details[0]

    def test_assert_invariants_fails_because_nothing_was_observed(self):
        report = probe(
            flaky_scorer(), [accuracy()], CASES, Contract(invariants=(CUE_CASE,))
        )
        with pytest.raises(InvariantViolation, match="no probe was executed"):
            assert_invariants(report, fail_on_error=False)


class TestBadTransformBlamedOnTheTransform:
    def test_undeclared_mutation_is_an_error_not_a_scorer_failure(self):
        bad = transform(
            "bad_target_mutator",
            [CUE_CASE],
            ["completion"],
            lambda c: Case(completion=c.completion.title(), target="CHANGED"),
        )
        report = probe(
            case_insensitive_scorer(),
            [accuracy()],
            CASES,
            Contract(invariants=(CUE_CASE,)),
            transforms=[bad],
        )
        r = _result(report, "CUE_CASE", "bad_target_mutator")
        assert r.outcome is Outcome.ERROR
        assert "TRANSFORM_CONTRACT_VIOLATED" in r.details[0]
        assert report.failures == () or all(
            f.transformation != "bad_target_mutator" for f in report.failures
        )

    def test_a_raising_transform_is_an_error(self):
        def boom(_case):
            raise RuntimeError("transform exploded")

        bad = transform("boomer", [CUE_CASE], ["completion"], boom)
        report = probe(
            case_insensitive_scorer(),
            [accuracy()],
            CASES,
            Contract(invariants=(CUE_CASE,)),
            transforms=[bad],
        )
        r = _result(report, "CUE_CASE", "boomer")
        assert r.outcome is Outcome.ERROR
        assert "TRANSFORM_RAISED" in r.details[0]

    def test_a_no_op_transform_is_not_applicable_never_a_pass(self):
        noop = transform("noop", [CUE_CASE], ["completion"], lambda c: c)
        report = probe(
            case_insensitive_scorer(),
            [accuracy()],
            CASES,
            Contract(invariants=(CUE_CASE,)),
            transforms=[noop],
        )
        assert _result(report, "CUE_CASE", "noop").outcome is Outcome.NOT_APPLICABLE


class TestNoApplicableTransform:
    def test_invariant_with_no_transformation_is_not_applicable(self):
        # no builtin declares that it tests WRONG_STAYS_INCORRECT or CODE_FORMATTING yet
        report = probe(
            case_insensitive_scorer(),
            [accuracy()],
            CASES,
            Contract(invariants=(WRONG_STAYS_INCORRECT, CODE_FORMATTING)),
        )
        for name in ("WRONG_STAYS_INCORRECT", "CODE_FORMATTING"):
            r = _result(report, name, "-")
            assert r.outcome is Outcome.NOT_APPLICABLE
            assert "no transformation declares" in r.details[0]

    def test_a_contract_that_observes_nothing_fails_the_assertion(self):
        report = probe(
            case_insensitive_scorer(),
            [accuracy()],
            CASES,
            Contract(invariants=(WRONG_STAYS_INCORRECT,)),
        )
        assert report.probes_executed == 0
        with pytest.raises(InvariantViolation, match="no probe was executed"):
            assert_invariants(report)


class TestReproduction:
    def test_absent_without_scorer_source(self):
        report = probe(
            case_sensitive_scorer(), [accuracy()], CASES, Contract(invariants=(CUE_CASE,))
        )
        repro = report.failures[0].reproduction
        assert repro is not None
        assert repro.code is None, "must not fabricate source it cannot reconstruct"
        # the WHOLE case list, not just the first changed pair: a metric-layer finding cannot be
        # reproduced from one case, because an aggregate only moves once every case is scored
        assert len(repro.baseline_cases) == len(CASES)
        assert len(repro.transformed_cases) == len(CASES)
        assert repro.baseline_cases[0].completion == "ANSWER: TRUE"
        assert repro.transformed_cases[0].completion != repro.baseline_cases[0].completion
        assert repro.changed_case_indices == (0, 1)

    def test_present_when_the_scorer_is_reconstructible(self):
        report = probe(
            case_sensitive_scorer(),
            [accuracy()],
            CASES,
            Contract(invariants=(CUE_CASE,)),
            scorer_source="case_sensitive_scorer()",
        )
        code = report.failures[0].reproduction.code
        assert code is not None
        assert "case_sensitive_scorer()" in code
        # every case must appear, or the snippet does not reproduce a metric-layer finding
        for c in CASES:
            assert repr(c) in code
        assert "'accuracy'" in code, "the metric names must be stated"

    def test_is_a_plain_dataclass_so_it_serialises_without_a_helper(self):
        from dataclasses import asdict

        report = probe(
            case_sensitive_scorer(), [accuracy()], CASES, Contract(invariants=(CUE_CASE,))
        )
        d = asdict(report.failures[0].reproduction)
        assert d["invariant"] == "CUE_CASE"
        assert len(d["baseline_cases"]) == len(CASES)
        assert d["changed_case_indices"] == (0, 1)


class TestReportRendering:
    def test_grid_lists_every_result_and_the_contract_hash(self):
        report = probe(
            case_sensitive_scorer(),
            {"accuracy": accuracy(), "weighted": upper_keyed_accuracy()},
            CASES,
            Contract(invariants=(CUE_CASE, MARKUP), exclusions=(CODE_FORMATTING,)),
        )
        text = report.render()
        assert report.contract_hash[:12] in text
        assert "CUE_CASE" in text
        assert "CODE_FORMATTING" in text
        assert "EXCLUDED" in text
        assert "executed" in text

    def test_counts_cover_every_outcome(self):
        report = probe(
            case_sensitive_scorer(),
            [accuracy()],
            CASES,
            Contract(invariants=(CUE_CASE,), exclusions=(MARKUP,)),
        )
        counts = report.outcome_counts()
        assert set(counts) == {o.name for o in Outcome}
        assert counts["EXCLUDED"] == 1


class TestGuards:
    def test_empty_cases_rejected(self):
        with pytest.raises(ValueError, match="non-empty"):
            probe(
                case_insensitive_scorer(), [accuracy()], [], Contract(invariants=(CUE_CASE,))
            )

    def test_error_fails_the_assertion_by_default(self):
        bad = transform(
            "bad_target_mutator",
            [CUE_CASE],
            ["completion"],
            lambda c: Case(completion=c.completion.title(), target="CHANGED"),
        )
        report = probe(
            case_insensitive_scorer(),
            [accuracy()],
            CASES,
            Contract(invariants=(CUE_CASE,)),
            transforms=[bad],
        )
        assert report.errors
        # ERROR fails by default: a CI job exiting 0 on PASS + ERROR has converted
        # "could not observe" into "fine"
        with pytest.raises(InvariantViolation, match="could not be observed"):
            assert_invariants(report)
        # and warns instead when the caller explicitly opts into exploratory behaviour
        with pytest.warns(UserWarning, match="could not be observed"):
            assert_invariants(report, fail_on_error=False)


class TestToleranceEndToEnd:
    """Tolerance had unit tests but no end-to-end cell, which is an untested path in a detector."""

    def _report(self, tolerances):
        return probe(
            case_insensitive_scorer(),
            {"accuracy": accuracy(), "weighted": upper_keyed_accuracy()},
            CASES,
            Contract(invariants=(CUE_CASE,), tolerances=tolerances),
        )

    def test_a_tolerance_wide_enough_absorbs_the_failure(self):
        # 1.0 -> 0.0 is a move of 1.0, so an absolute tolerance of 1.0 permits it
        assert self._report({"weighted": Tolerance(absolute=1.0)}).failures == ()

    def test_a_narrow_tolerance_does_not(self):
        assert self._report({"weighted": Tolerance(absolute=0.1)}).failures

    def test_a_tolerance_on_a_different_metric_does_not_absorb_it(self):
        # tolerances are per-metric, never global
        assert self._report({"accuracy": Tolerance(absolute=1.0)}).failures

    def test_loosening_a_tolerance_changes_the_recorded_contract_hash(self):
        strict = self._report({}).contract_hash
        loose = self._report({"weighted": Tolerance(absolute=1.0)}).contract_hash
        assert strict != loose, "silencing a FAIL with tolerance must be visible in the record"


@metric
def dict_valued_metric():
    """Inspect metrics may return a dict. Such a metric cannot be compared as a scalar."""

    def compute(scores: list[SampleScore]) -> dict[str, float]:
        return {"a": 1.0, "b": 2.0}

    return compute


@metric
def nested_metric():
    """A nested aggregate: also not a scalar."""

    def compute(scores: list[SampleScore]) -> dict[str, object]:
        return {"outer": {"inner": [1.0, 2.0]}}

    return compute


class TestUncomparableMetricNeverPasses:
    """A requested observation must never silently disappear into PASS.

    PASS means the requested relation was tested and held. For a non-scalar metric it was never
    tested, so the honest outcome is ERROR -- an observation that could not be made.
    """

    def _report(self, metrics):
        return probe(
            case_insensitive_scorer(), metrics, CASES, Contract(invariants=(CUE_CASE,))
        )

    def test_dict_valued_metric_is_error_not_pass(self):
        r = self._report({"per_key": dict_valued_metric()}).results[0]
        assert r.outcome is Outcome.ERROR
        assert r.outcome is not Outcome.PASS
        assert any("UNCOMPARED_METRICS" in d for d in r.details)
        assert "per_key" in " ".join(r.details)

    def test_nested_metric_is_error_not_pass(self):
        r = self._report({"nested": nested_metric()}).results[0]
        assert r.outcome is Outcome.ERROR
        assert any("UNCOMPARED_METRICS" in d for d in r.details)
        assert "nested" in " ".join(r.details)

    def test_all_metrics_uncomparable(self):
        report = self._report({"a": dict_valued_metric(), "b": nested_metric()})
        r = report.results[0]
        assert r.outcome is Outcome.ERROR
        assert all(m.change is MetricChange.NOT_COMPARABLE for m in r.metrics)
        # nothing was observed, so the assertion must not pass either
        assert report.probes_executed == 0
        for kwargs in ({}, {"fail_on_error": False}):
            with pytest.raises(InvariantViolation, match="no probe was executed"):
                assert_invariants(report, **kwargs)

    def test_one_comparable_and_one_uncomparable_is_still_not_pass(self):
        # the comparable one held; that is not enough to claim the relation was tested
        report = self._report({"accuracy": accuracy(), "per_key": dict_valued_metric()})
        r = report.results[0]
        assert r.outcome is Outcome.ERROR
        by_name = {m.name: m.change for m in r.metrics}
        assert by_name["accuracy"] is MetricChange.UNCHANGED
        assert by_name["per_key"] is MetricChange.NOT_COMPARABLE

    def test_a_real_violation_still_reports_fail_not_error(self):
        # FAIL is more informative than "could not compare everything", so it wins
        report = probe(
            case_sensitive_scorer(),
            {"accuracy": accuracy(), "per_key": dict_valued_metric()},
            CASES,
            Contract(invariants=(CUE_CASE,)),
        )
        r = report.results[0]
        assert r.outcome is Outcome.FAIL
        assert any("UNCOMPARED_METRICS" in d for d in r.details), (
            "the FAIL must still disclose that a metric went uncompared"
        )

    def test_only_scalar_metrics_yields_a_clean_pass(self):
        r = self._report({"accuracy": accuracy()}).results[0]
        assert r.outcome is Outcome.PASS


class TestAsyncApi:
    """probe()/observe() are sync wrappers; the async entry points work inside a live loop."""

    def test_probe_async_works_inside_a_running_event_loop(self):
        async def main():
            return await probe_async(
                case_sensitive_scorer(),
                [accuracy()],
                CASES,
                Contract(invariants=(CUE_CASE,)),
            )

        report = asyncio.run(main())
        assert report.failures, "the async path must produce the same finding as the sync one"

    def test_observe_async_works_inside_a_running_event_loop(self):
        async def main():
            return await observe_async(
                case_insensitive_scorer(), resolve_metrics([accuracy()]), CASES
            )

        obs = asyncio.run(main())
        assert obs.metrics["accuracy"] == 1.0

    def test_sync_probe_inside_a_loop_fails_with_a_useful_message(self):
        async def main():
            with pytest.raises(RuntimeError, match=r"probe_async\(\) instead"):
                probe(
                    case_sensitive_scorer(),
                    [accuracy()],
                    CASES,
                    Contract(invariants=(CUE_CASE,)),
                )

        asyncio.run(main())

    def test_sync_observe_inside_a_loop_fails_with_a_useful_message(self):
        async def main():
            with pytest.raises(RuntimeError, match=r"observe_async\(\) instead"):
                observe(case_insensitive_scorer(), resolve_metrics([accuracy()]), CASES)

        asyncio.run(main())

    def test_sync_and_async_agree(self):
        args = (case_sensitive_scorer(), [accuracy()], CASES, Contract(invariants=(CUE_CASE,)))
        sync = probe(*args)
        which = asyncio.run(probe_async(*args))
        assert [r.outcome for r in sync.results] == [r.outcome for r in which.results]
        assert sync.contract_hash == which.contract_hash


class TestDuplicateCaseThroughThePublicPath:
    """verify.py unit-tests duplicate detection; this exercises it through probe()."""

    def _dup_transform(self):
        # [A, B, C] -> [A, A, C]: the count is preserved, but case 1 has been replaced by a copy
        # of case 0, which silently reweights every aggregate metric
        def apply(case: Case) -> Case | None:
            if case.completion == "ANSWER: B":
                return case.with_completion("ANSWER: A")
            return None

        return transform("duplicator", [CUE_CASE], ["completion"], apply)

    def _report(self):
        # the three cases share a target, because Case equality covers every field -- with
        # different targets the rewritten case would not be a duplicate of case 0 at all, which
        # is what an earlier version of this test got wrong
        cases = [
            Case(completion="ANSWER: A", target="A"),
            Case(completion="ANSWER: B", target="A"),
            Case(completion="ANSWER: C", target="A"),
        ]
        return probe(
            case_insensitive_scorer(),
            [accuracy()],
            cases,
            Contract(invariants=(CUE_CASE,)),
            transforms=[self._dup_transform()],
        )

    def test_is_an_error(self):
        r = next(x for x in self._report().results if x.transformation == "duplicator")
        assert r.outcome is Outcome.ERROR

    def test_names_case_duplicated(self):
        r = next(x for x in self._report().results if x.transformation == "duplicator")
        assert "CASE_DUPLICATED" in " ".join(r.details).upper()

    def test_is_blamed_on_the_transformation_not_the_scorer(self):
        r = next(x for x in self._report().results if x.transformation == "duplicator")
        detail = " ".join(r.details)
        assert "TRANSFORM_CONTRACT_VIOLATED" in detail
        assert "duplicator" in detail
        assert self._report().failures == () or all(
            f.transformation != "duplicator" for f in self._report().failures
        )


class TestBaselineFailureThroughThePublicApi:
    """A scorer that fails during the BASELINE must not leak an exception out of probe()."""

    def test_raising_scorer_yields_a_structured_error_report(self):
        report = probe(
            raising_scorer(), [accuracy()], CASES, Contract(invariants=(CUE_CASE,))
        )
        assert len(report.errors) == 1
        assert report.failures == ()
        detail = report.errors[0].details[0]
        assert "BASELINE_OBSERVATION_FAILED" in detail

    def test_the_exception_information_is_preserved_not_swallowed(self):
        report = probe(
            raising_scorer(), [accuracy()], CASES, Contract(invariants=(CUE_CASE,))
        )
        detail = report.errors[0].details[0]
        assert "RuntimeError" in detail
        assert "scorer exploded" in detail

    def test_a_none_score_during_baseline_is_also_structured(self):
        report = probe(
            none_scorer(), [accuracy()], CASES, Contract(invariants=(CUE_CASE,))
        )
        assert len(report.errors) == 1
        assert "returned None" in report.errors[0].details[0]

    def test_the_assertion_fails_rather_than_passing_on_an_unobservable_baseline(self):
        report = probe(
            raising_scorer(), [accuracy()], CASES, Contract(invariants=(CUE_CASE,))
        )
        with pytest.raises(InvariantViolation):
            assert_invariants(report)

    def test_async_path_behaves_identically(self):
        async def main():
            return await probe_async(
                raising_scorer(), [accuracy()], CASES, Contract(invariants=(CUE_CASE,))
            )

        report = asyncio.run(main())
        assert "BASELINE_OBSERVATION_FAILED" in report.errors[0].details[0]
