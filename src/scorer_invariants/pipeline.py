"""Running a scoring pipeline and observing it.

An observation is per-case verdicts plus aggregate metric values. Everything here is offline:
no providers, no network, no sandbox. A scorer that needs any of those will surface as an ERROR
or as a non-repeatable baseline rather than as a quiet result.
"""

from __future__ import annotations

import asyncio
import inspect
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast

from inspect_ai.model import ModelName, ModelOutput
from inspect_ai.scorer import Metric, SampleScore, Score, Scorer, Target
from inspect_ai.scorer._metric import MetricDeprecated, MetricProtocol
from inspect_ai.solver import TaskState

from .case import Case

#: Placeholder model name. No model is ever called; the scorer only reads the output we supply.
PROBE_MODEL = "mockllm/model"


class NonRepeatableBaseline(RuntimeError):
    """The same inputs produced different observations across repeated runs.

    Every comparison downstream would be meaningless, so this stops the probe. It is never
    reported as a scorer FAIL.
    """


@dataclass(frozen=True)
class Observation:
    """One run of the pipeline over a case list."""

    verdicts: tuple[Any, ...]
    metrics: Mapping[str, Any]
    scores: tuple[Score, ...]

    def __len__(self) -> int:
        return len(self.verdicts)


def metric_name(metric: Metric, fallback_index: int) -> str:
    """Best-effort name for a metric.

    Inspect records names in a private registry (`inspect_ai._util.registry`), so this is
    opportunistic: if that API moves, naming degrades to `metric_0` rather than the package
    breaking. Callers who care can pass a {name: metric} mapping instead.
    """
    try:
        from inspect_ai._util.registry import registry_info

        name = registry_info(metric).name
        return name.split("/", 1)[1] if "/" in name else name
    except Exception:  # noqa: BLE001 - registry is private; degrade, never break
        return f"metric_{fallback_index}"


def resolve_metrics(
    metrics: Sequence[Metric] | Mapping[str, Metric],
) -> dict[str, Metric]:
    if isinstance(metrics, Mapping):
        return dict(metrics)
    resolved: dict[str, Metric] = {}
    for index, metric in enumerate(metrics):
        name = metric_name(metric, index)
        # two metrics can legitimately share a registry name; keep both distinguishable
        if name in resolved:
            name = f"{name}_{index}"
        resolved[name] = metric
    return resolved


def to_task_state(case: Case, index: int) -> TaskState:
    """Adapt a Case into the TaskState a scorer reads.

    Deliberately minimal: the scorer sees the completion, the metadata and the messages the case
    supplies, and nothing invented on its behalf.
    """
    return TaskState(
        model=ModelName(PROBE_MODEL),
        sample_id=index + 1,
        epoch=1,
        input="",
        messages=list(case.messages or []),
        metadata=dict(case.metadata or {}),
        output=ModelOutput.from_content(PROBE_MODEL, case.completion),
    )


def _target(case: Case) -> Target:
    return Target(case.target if isinstance(case.target, list) else [case.target])


async def score_cases(scorer: Scorer, cases: Sequence[Case]) -> list[SampleScore]:
    out: list[SampleScore] = []
    for index, case in enumerate(cases):
        score = await scorer(to_task_state(case, index), _target(case))
        if score is None:
            raise ValueError(
                f"scorer returned None for case {index}; the probe cannot compare a "
                "missing score"
            )
        out.append(SampleScore(score=score, sample_id=index + 1))
    return out


def _takes_sample_scores(metric: Metric) -> bool:
    """Which of Inspect's two metric signatures this is.

    `Metric` is a union: MetricProtocol takes list[SampleScore], the deprecated form takes
    list[Score]. Dispatch on the annotation rather than by catching TypeError, which would
    swallow a genuine TypeError raised inside the metric itself. Unannotated metrics are assumed
    modern.
    """
    try:
        params = list(inspect.signature(metric).parameters.values())
    except (TypeError, ValueError):
        return True
    if not params:
        return True
    return "Score]" not in str(params[0].annotation) or "SampleScore]" in str(
        params[0].annotation
    )


def compute_metrics(
    metrics: Mapping[str, Metric], sample_scores: list[SampleScore]
) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for name, metric in metrics.items():
        if _takes_sample_scores(metric):
            values[name] = cast("MetricProtocol", metric)(sample_scores)
        else:
            values[name] = cast("MetricDeprecated", metric)(
                [s.score for s in sample_scores]
            )
    return values


async def observe_async(
    scorer: Scorer,
    metrics: Mapping[str, Metric],
    cases: Sequence[Case],
) -> Observation:
    sample_scores = await score_cases(scorer, cases)
    return Observation(
        verdicts=tuple(s.score.value for s in sample_scores),
        metrics=compute_metrics(metrics, sample_scores),
        scores=tuple(s.score for s in sample_scores),
    )


def observe(
    scorer: Scorer,
    metrics: Mapping[str, Metric],
    cases: Sequence[Case],
) -> Observation:
    """Synchronous wrapper, for use from a pytest test rather than inside a running eval."""
    return asyncio.run(observe_async(scorer, metrics, cases))


def _values_agree(value: Any, other: Any) -> bool:
    """Equality that treats NaN as equal to itself.

    `nan != nan`, so a bare comparison reports an all-NaN observation as unstable. This applies to
    verdicts exactly as much as to metrics -- a Score.value can be NaN too, which is how the first
    version of this function wrongly flagged a perfectly repeatable scorer.
    """
    if isinstance(value, float) and isinstance(other, float) and math.isnan(value) and math.isnan(other):
        return True
    return bool(value == other)


def _observations_agree(a: Observation, b: Observation) -> bool:
    if len(a.verdicts) != len(b.verdicts):
        return False
    if not all(_values_agree(x, y) for x, y in zip(a.verdicts, b.verdicts)):
        return False
    if set(a.metrics) != set(b.metrics):
        return False
    return all(_values_agree(v, b.metrics[name]) for name, v in a.metrics.items())


def baseline(
    scorer: Scorer,
    metrics: Mapping[str, Metric],
    cases: Sequence[Case],
    repeatability_runs: int = 2,
) -> Observation:
    """Observe the pipeline `repeatability_runs` times and require the runs to agree.

    This establishes REPEATABILITY across the configured runs, not determinism -- a judge at
    temperature 0, or two lucky draws, would pass. It is still worth doing: it catches most
    model-graded scorers, and it makes it impossible for the tool to report sampling noise as a
    defect.
    """
    if repeatability_runs < 1:
        raise ValueError("repeatability_runs must be at least 1")

    first = observe(scorer, metrics, cases)
    for run in range(2, repeatability_runs + 1):
        again = observe(scorer, metrics, cases)
        if not _observations_agree(first, again):
            raise NonRepeatableBaseline(
                f"run 1 and run {run} disagree on identical inputs; "
                f"verdicts {first.verdicts} vs {again.verdicts}, "
                f"metrics {dict(first.metrics)} vs {dict(again.metrics)}"
            )
    return first
