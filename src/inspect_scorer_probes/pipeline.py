"""Running a scoring pipeline and observing it.

An observation is per-case verdicts plus aggregate metric values.

OFFLINE AND DETERMINISTIC IS A PRECONDITION, NOT A GUARANTEE. V1 requires the scorer under test to
make no provider call, no network request and no sandbox call, and not to depend on a clock or an
RNG. The package does **not** enforce this: it does not sandbox the scorer, intercept sockets, or
inspect what the scorer calls. Hand it a model-graded scorer and it may quietly produce a result,
and that result will be meaningless.

The repeatability check in `baseline_async` is a weak safety net over that precondition, not
enforcement. It observes the baseline N times and requires the observations to agree, which catches
a scorer whose output varies across those N runs. It cannot catch a judge at temperature 0, a cached
response, or any dependence that happens to be stable within one session.

Meeting the precondition is the caller's responsibility.
"""

from __future__ import annotations

import asyncio
import inspect
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast, get_type_hints

from inspect_ai.model import ModelName, ModelOutput
from inspect_ai.scorer import Metric, SampleScore, Scorer, Target
from inspect_ai.solver import TaskState

if TYPE_CHECKING:  # these names are only needed by the type checker, so no runtime import of a
    # private inspect_ai module -- an unguarded one would make the package fail to import at all
    # if that module ever moves
    from inspect_ai.scorer._metric import MetricDeprecated, MetricProtocol

from .case import Case

#: Placeholder model name. No model is ever called; the scorer only reads the output we supply.
PROBE_MODEL = "mockllm/model"


class NonRepeatableBaseline(RuntimeError):
    """Repeated observations of the same inputs disagreed.

    Every comparison downstream would be meaningless, so this stops the probe. It is never
    reported as a scorer FAIL.
    """


@dataclass(frozen=True)
class Observation:
    """One run of the pipeline over a case list."""

    verdicts: tuple[Any, ...]
    metrics: Mapping[str, Any]

    def __len__(self) -> int:
        return len(self.verdicts)


def _require_no_running_loop(name: str) -> None:
    """Fail with a useful message rather than asyncio's when called from async code."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return
    raise RuntimeError(
        f"{name}() is a synchronous convenience wrapper and cannot be called while an event "
        f"loop is running. Use {name}_async() instead -- for example from an async test, or "
        "from inside an Inspect solver or scorer."
    )


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

    Deliberately minimal, and this is V1's scope limit: the scorer sees the input, completion,
    metadata and messages the Case supplies, and nothing invented on its behalf. A scorer that
    reads anything else off TaskState -- the store, `output.choices`, a sandbox -- is outside what
    a Case can represent, and therefore outside V1.
    """
    return TaskState(
        model=ModelName(PROBE_MODEL),
        sample_id=index + 1,
        epoch=1,
        input=case.input,
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


def _call_metric(metric: Metric, sample_scores: list[SampleScore]) -> Any:
    """Call a metric the way a real eval would.

    Inspect supports two metric signatures -- MetricProtocol takes list[SampleScore], the
    deprecated form takes list[Score] -- and decides which to use in `is_metric_deprecated`.
    Crucially, when a metric has no parameter or no usable type hint, Inspect treats it as
    DEPRECATED and passes list[Score].

    An earlier version of this function assumed the opposite. That meant an unannotated metric
    received SampleScore here and Score in a real eval, so the value this package compared was not
    the value the eval would report -- which silently invalidates the comparison. It was caught by
    running a fixture through inspect_ai.eval() and finding the baseline metric wrong.

    So we defer to Inspect's own dispatch where we can, which makes drift impossible. The fallback
    mirrors Inspect's rule rather than guessing.
    """
    try:
        from inspect_ai._eval.task.results import call_metric

        return call_metric(metric, sample_scores)
    except ImportError:  # pragma: no cover - private API moved
        if _is_deprecated_signature(metric):
            return cast("MetricDeprecated", metric)([s.score for s in sample_scores])
        return cast("MetricProtocol", metric)(sample_scores)


def _is_deprecated_signature(metric: Metric) -> bool:
    """Mirror of Inspect's `is_metric_deprecated`: no param or no usable hint means deprecated."""
    try:
        params = list(inspect.signature(metric).parameters.values())
        hints = get_type_hints(metric)
    except (TypeError, ValueError, NameError):
        return True
    if not params:
        return True
    expected = hints.get(params[0].name)
    if expected is None or expected is Any:
        return True
    return "SampleScore" not in str(expected)


def compute_metrics(
    metrics: Mapping[str, Metric], sample_scores: list[SampleScore]
) -> dict[str, Any]:
    return {name: _call_metric(metric, sample_scores) for name, metric in metrics.items()}


async def observe_async(
    scorer: Scorer,
    metrics: Mapping[str, Metric],
    cases: Sequence[Case],
) -> Observation:
    sample_scores = await score_cases(scorer, cases)
    return Observation(
        verdicts=tuple(s.score.value for s in sample_scores),
        metrics=compute_metrics(metrics, sample_scores),
    )


def observe(
    scorer: Scorer,
    metrics: Mapping[str, Metric],
    cases: Sequence[Case],
) -> Observation:
    """Synchronous wrapper around `observe_async`. Not usable inside a running event loop."""
    _require_no_running_loop("observe")
    return asyncio.run(observe_async(scorer, metrics, cases))


def _values_agree(value: Any, other: Any) -> bool:
    """Equality that treats NaN as equal to itself.

    `nan != nan`, so a bare comparison reports an all-NaN observation as unstable. This applies to
    verdicts exactly as much as to metrics -- a Score.value can be NaN too, which is how the first
    version of this function wrongly flagged a perfectly repeatable scorer.
    """
    if (
        isinstance(value, float)
        and isinstance(other, float)
        and math.isnan(value)
        and math.isnan(other)
    ):
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


async def baseline_async(
    scorer: Scorer,
    metrics: Mapping[str, Metric],
    cases: Sequence[Case],
    repeatability_runs: int = 2,
) -> Observation:
    """Observe the pipeline `repeatability_runs` times and require the runs to agree.

    This establishes REPEATABILITY across the configured runs. It does not establish determinism,
    and it does not establish that the scorer is offline -- see the module docstring. A judge at
    temperature 0, a cached response, or any dependence stable within one session passes it.
    """
    if repeatability_runs < 1:
        raise ValueError("repeatability_runs must be at least 1")

    first = await observe_async(scorer, metrics, cases)
    for run in range(2, repeatability_runs + 1):
        again = await observe_async(scorer, metrics, cases)
        if not _observations_agree(first, again):
            raise NonRepeatableBaseline(
                f"run 1 and run {run} disagree on identical inputs; "
                f"verdicts {first.verdicts} vs {again.verdicts}, "
                f"metrics {dict(first.metrics)} vs {dict(again.metrics)}"
            )
    return first


def baseline(
    scorer: Scorer,
    metrics: Mapping[str, Metric],
    cases: Sequence[Case],
    repeatability_runs: int = 2,
) -> Observation:
    """Synchronous wrapper around `baseline_async`. Not usable inside a running event loop."""
    _require_no_running_loop("baseline")
    return asyncio.run(baseline_async(scorer, metrics, cases, repeatability_runs))
