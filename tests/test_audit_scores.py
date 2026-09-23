"""Controls N6-N7 from validation/diff/PREREG.md, and the four score-diff cases, on REAL Inspect logs
produced with mockllm (no API key, no network)."""

from __future__ import annotations

from typing import Any

import pytest
from inspect_ai import Task, score
from inspect_ai import eval as inspect_eval
from inspect_ai.dataset import MemoryDataset, Sample
from inspect_ai.log import EvalLog
from inspect_ai.model import ModelOutput, get_model
from inspect_ai.scorer import (
    CORRECT,
    INCORRECT,
    Score,
    Scorer,
    Target,
    accuracy,
    includes,
    match,
    metric,
    model_graded_qa,
    scorer,
)
from inspect_ai.solver import TaskState

from inspect_audit import diff_logs, scoring_model_calls

TARGETS = ["Paris", "Berlin", "Rome", "Madrid"]
ANSWERS = ["Paris", "The answer is Berlin", "Rome", "Lisbon"]   # match() vs includes() differ on 1


def run(scorer_: Scorer, tmp_path: Any, answers: list[str] = ANSWERS) -> EvalLog:
    ds = MemoryDataset([Sample(id=i, input=f"capital {i}?", target=t) for i, t in enumerate(TARGETS)])
    model = get_model("mockllm/model",
                      custom_outputs=[ModelOutput.from_content("mockllm/model", a) for a in answers])
    return inspect_eval(Task(dataset=ds, scorer=scorer_), model=model, display="none",
                        log_dir=str(tmp_path))[0]


def rescore(log: EvalLog, scorer_: Scorer) -> EvalLog:
    return score(log, scorer_, action="overwrite", display="none", model="mockllm/model")


def test_n6_log_vs_itself_is_empty(tmp_path: Any) -> None:
    log = run(match(), tmp_path)
    d = diff_logs(log, log)
    assert d.refused is None and d.empty


def test_rescoring_with_the_same_scorer_is_empty(tmp_path: Any) -> None:
    log = run(match(), tmp_path)
    d = diff_logs(log, rescore(log, match()))
    assert d.refused is None and d.empty


@scorer(metrics=[accuracy()], name="exact")
def exact() -> Scorer:
    async def s(state: TaskState, target: Target) -> Score:
        return Score(value=CORRECT if state.output.completion == target.text else INCORRECT)
    return s


def test_verdicts_changed_metrics_changed(tmp_path: Any) -> None:
    before = run(exact(), tmp_path)
    # same scorer NAME, different logic, so the diff compares like with like
    @scorer(metrics=[accuracy()], name="exact")
    def exact_includes() -> Scorer:
        inner = includes()
        async def s(state: TaskState, target: Target) -> Score:
            return await inner(state, target)  # type: ignore[no-any-return]
        return s
    after = rescore(before, exact_includes())
    d = diff_logs(before, after)
    sd = d.scorers[0]
    assert sd.case == "verdicts changed, metrics changed"
    assert sd.transitions == {"'I' -> 'C'": 1}
    assert sd.examples["'I' -> 'C'"] == ["1"]


@metric(name="accuracy")
def generous() -> Any:
    def m(scores: list[Any]) -> float:
        return 1.0
    return m


def test_verdicts_unchanged_metrics_changed(tmp_path: Any) -> None:
    @scorer(metrics=[accuracy()], name="exact")
    def exact_a() -> Scorer:
        return exact()
    @scorer(metrics=[generous()], name="exact")
    def exact_b() -> Scorer:
        return exact()
    before = run(exact_a(), tmp_path)
    after = rescore(before, exact_b())
    sd = diff_logs(before, after).scorers[0]
    assert sd.case == "verdicts unchanged, metrics changed"
    assert not sd.transitions


def test_n7_model_graded_scoring_is_refused(tmp_path: Any) -> None:
    grader = get_model("mockllm/model", custom_outputs=[
        ModelOutput.from_content("mockllm/model", "GRADE: C")] * 8)
    log = run(model_graded_qa(model=grader), tmp_path)
    assert scoring_model_calls(log) > 0
    d = diff_logs(log, log)
    assert d.refused is not None and "called a model" in d.refused
    assert d.scorers == [] and not d.empty


def test_deterministic_scoring_has_no_scoring_model_calls(tmp_path: Any) -> None:
    assert scoring_model_calls(run(match(), tmp_path)) == 0


def test_different_transcripts_are_refused(tmp_path: Any) -> None:
    a = run(match(), tmp_path / "a")
    b = run(match(), tmp_path / "b", answers=["Paris", "Berlin", "Rome", "Madrid"])
    d = diff_logs(a, b)
    assert d.refused is not None and "different transcripts" in d.refused


def test_header_only_log_is_refused(tmp_path: Any) -> None:
    from inspect_ai.log import read_eval_log
    log = run(match(), tmp_path)
    header = read_eval_log(log.location, header_only=True)
    d = diff_logs(header, log)
    assert d.refused is not None and "no samples" in d.refused


def test_cli_exit_codes(tmp_path: Any) -> None:
    from inspect_audit.cli import main
    log = run(match(), tmp_path)
    assert main(["diff", "scores", log.location, log.location]) == 0
    assert main(["diff", "scores", log.location, str(tmp_path / "missing.eval")]) == 2


pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")
