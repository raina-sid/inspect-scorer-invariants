from __future__ import annotations

import itertools

import pytest
from inspect_ai.scorer import CORRECT, INCORRECT, Score, accuracy, mean, scorer, stderr

from inspect_scorer_probes.case import Case
from inspect_scorer_probes.pipeline import (
    NonRepeatableBaseline,
    baseline,
    observe,
    resolve_metrics,
    to_task_state,
)

CASES = [
    Case(completion="ANSWER: TRUE", target="TRUE", metadata={"k": 1}),
    Case(completion="ANSWER: FALSE", target="TRUE", metadata={"k": 2}),
]

METRICS = resolve_metrics([accuracy(), stderr()])


@scorer(metrics=[accuracy()])
def exact_tail_scorer():
    """CORRECT when the completion ends with the target."""

    async def score(state, target):
        return Score(value=CORRECT if state.output.completion.endswith(target.text) else INCORRECT)

    return score


@scorer(metrics=[accuracy()])
def metadata_scorer():
    """Reads state.metadata, as tau2's scorer does."""

    async def score(state, target):
        return Score(value=CORRECT if state.metadata.get("k") == 1 else INCORRECT)

    return score


@scorer(metrics=[accuracy()])
def flaky_scorer(cases_per_run: int = 2):
    """Flips verdict on every RUN, without any model involved.

    An earlier version alternated per *call* with period 2, which over 2 cases made it
    accidentally repeatable -- run 1 saw calls 0,1 and run 2 saw calls 2,3, both (C, I). The
    flip has to happen on the run boundary to be genuinely unstable.
    """
    counter = itertools.count()

    async def score(state, target):
        run = next(counter) // cases_per_run
        return Score(value=CORRECT if run % 2 == 0 else INCORRECT)

    return score


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


class TestTaskStateAdapter:
    def test_completion_reaches_the_scorer(self):
        st = to_task_state(Case(completion="hello", target="x"), 0)
        assert st.output.completion == "hello"

    def test_metadata_reaches_the_scorer(self):
        st = to_task_state(Case(completion="c", target="x", metadata={"k": 7}), 0)
        assert st.metadata["k"] == 7

    def test_metadata_is_copied_not_shared(self):
        # a scorer that mutates state.metadata must not corrupt the Case
        case = Case(completion="c", target="x", metadata={"k": 1})
        st = to_task_state(case, 0)
        st.metadata["k"] = 99
        assert case.metadata == {"k": 1}

    def test_sample_ids_are_one_based_and_distinct(self):
        assert to_task_state(CASES[0], 0).sample_id == 1
        assert to_task_state(CASES[1], 1).sample_id == 2

    def test_no_messages_yields_an_empty_list_not_none(self):
        assert to_task_state(Case(completion="c", target="x"), 0).messages == []


class TestObserve:
    def test_verdicts_and_metrics(self):
        obs = observe(exact_tail_scorer(), METRICS, CASES)
        assert obs.verdicts == (CORRECT, INCORRECT)
        assert obs.metrics["accuracy"] == 0.5
        assert len(obs) == 2

    def test_metadata_reading_scorer(self):
        obs = observe(metadata_scorer(), METRICS, CASES)
        assert obs.verdicts == (CORRECT, INCORRECT)

    def test_scorer_exception_propagates_rather_than_scoring_zero(self):
        with pytest.raises(RuntimeError, match="scorer exploded"):
            observe(raising_scorer(), METRICS, CASES)

    def test_none_score_is_an_error_not_a_verdict(self):
        with pytest.raises(ValueError, match="returned None"):
            observe(none_scorer(), METRICS, CASES)


class TestRepeatability:
    def test_stable_scorer_passes(self):
        obs = baseline(exact_tail_scorer(), METRICS, CASES, repeatability_runs=2)
        assert obs.verdicts == (CORRECT, INCORRECT)

    def test_flaky_scorer_is_non_repeatable_not_a_fail(self):
        with pytest.raises(NonRepeatableBaseline, match="disagree on identical inputs"):
            baseline(flaky_scorer(), METRICS, CASES, repeatability_runs=2)

    def test_one_run_skips_the_check(self):
        # explicitly opting out; the flaky scorer is not detected with a single run
        obs = baseline(flaky_scorer(), METRICS, CASES, repeatability_runs=1)
        assert len(obs) == 2

    def test_more_runs_still_pass_for_a_stable_scorer(self):
        obs = baseline(exact_tail_scorer(), METRICS, CASES, repeatability_runs=5)
        assert obs.metrics["accuracy"] == 0.5

    def test_zero_runs_rejected(self):
        with pytest.raises(ValueError, match="at least 1"):
            baseline(exact_tail_scorer(), METRICS, CASES, repeatability_runs=0)

    def test_an_all_nan_metric_is_not_mistaken_for_instability(self):
        @scorer(metrics=[mean()])
        def nan_metric_scorer():
            async def score(state, target):
                return Score(value=float("nan"))

            return score

        # nan != nan, so a naive agreement check would call this flaky
        obs = baseline(nan_metric_scorer(), resolve_metrics([mean()]), CASES, repeatability_runs=3)
        assert len(obs) == 2


class TestMetricNaming:
    def test_registry_names_are_unqualified(self):
        names = set(resolve_metrics([accuracy(), stderr()]))
        assert names == {"accuracy", "stderr"}

    def test_mapping_is_passed_through(self):
        m = resolve_metrics({"my_name": accuracy()})
        assert set(m) == {"my_name"}

    def test_duplicate_names_stay_distinguishable(self):
        m = resolve_metrics([accuracy(), accuracy()])
        assert len(m) == 2
