"""The worldsense defect must survive Inspect's OWN scoring and metric path, not just ours.

The package's central claim is that a metric-layer defect is invisible at the scorer layer. If that
only showed up through this package's `observe()`, it could be an artefact of our adapter. This test
runs the same reduction through `inspect_ai.eval()` -- real task, real scorer dispatch, real metric
aggregation -- and asserts the same four facts.
"""

from __future__ import annotations

import pytest
from inspect_ai import Task
from inspect_ai import eval as inspect_eval
from inspect_ai.dataset import MemoryDataset, Sample
from inspect_ai.model import ModelOutput, get_model
from inspect_ai.scorer import accuracy
from inspect_ai.solver import generate

from .fixtures import worldsense_scorer_reduction, ws_accuracy_reduction

#: Mirrors WORLDSENSE_CASES: each model output matches its own sample's target, so the BASELINE is
#: fully correct. An earlier version of this fixture emitted "TRUE" against alternating
#: TRUE/FALSE targets, which made accuracy legitimately 0.5 and the test wrong rather than the code.
TARGETS = ["TRUE", "FALSE", "TRUE", "FALSE"]


def _metrics_from_eval(case_fn, tmp_path) -> dict[str, float]:
    dataset = MemoryDataset(
        [Sample(input="pick one", target=t, id=i + 1) for i, t in enumerate(TARGETS)]
    )
    task = Task(
        dataset=dataset,
        solver=generate(),
        scorer=worldsense_scorer_reduction(),
        metrics=[accuracy(), ws_accuracy_reduction()],
    )
    model = get_model(
        "mockllm/model",
        custom_outputs=[
            ModelOutput.from_content("mockllm/model", case_fn(t)) for t in TARGETS
        ],
    )
    log = inspect_eval(task, model=model, log_dir=str(tmp_path), display="none")[0]
    assert log.status == "success", log.error
    assert log.results is not None
    out: dict[str, float] = {}
    for score in log.results.scores:
        for name, value in score.metrics.items():
            out[name] = value.value
    return out


@pytest.mark.parametrize(
    ("label", "case_fn", "expect_ws"),
    [("baseline UPPERCASE", str.upper, 1.0), ("CUE_CASE titlecase", str.title, 0.0)],
)
def test_worldsense_reduction_through_real_inspect_eval(label, case_fn, expect_ws, tmp_path):
    metrics = _metrics_from_eval(case_fn, tmp_path)
    # accuracy is unmoved either way: the scorer accepts both cases
    assert metrics["accuracy"] == 1.0, label
    # the weighted metric collapses for the title-cased answer
    assert metrics["ws_accuracy_reduction"] == expect_ws, label


def test_the_collapse_is_zero_not_nan_through_the_real_path(tmp_path):
    # NaN would announce itself; 0.0 is indistinguishable from a model that answered everything
    # wrong. Pinning this through Inspect's own aggregation, not only ours.
    import math

    value = _metrics_from_eval(str.title, tmp_path)["ws_accuracy_reduction"]
    assert value == 0.0
    assert not math.isnan(value)
