"""End-to-end tests of probe() and assert_invariants()."""

from __future__ import annotations

import itertools

import pytest
from inspect_ai.scorer import CORRECT, INCORRECT, Score, accuracy, metric, scorer

from scorer_invariants import (
    Case,
    Contract,
    InvariantViolation,
    Outcome,
    assert_invariants,
    probe,
    transform,
)
from scorer_invariants.invariants import (
    CODE_FORMATTING,
    CUE_CASE,
    CUE_WHITESPACE,
    MARKUP,
    WRONG_STAYS_INCORRECT,
)

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

    def compute(scores):
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
            assert_invariants(report, warn_on_error=False)


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

    def test_as_dict_is_serialisable(self):
        report = probe(
            case_sensitive_scorer(), [accuracy()], CASES, Contract(invariants=(CUE_CASE,))
        )
        d = report.failures[0].reproduction.as_dict()
        assert d["invariant"] == "CUE_CASE"
        assert d["relation"] == "equal"
        assert len(d["baseline_cases"]) == len(CASES)
        assert d["changed_case_indices"] == [0, 1]


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

    def test_error_warns_rather_than_passing_silently(self):
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
        with pytest.warns(UserWarning, match="could not be observed"):
            assert_invariants(report)
