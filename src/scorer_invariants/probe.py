"""The public entry point: observe a scoring pipeline under a declared contract.

    given a contract C and a transformation T, does pipeline P satisfy C?

Nothing here decides whether C is right for the task. That judgment is the caller's, and it is
recorded in the report along with a hash of it.

THE EPISTEMIC RULE, which the outcome routing exists to enforce:

    PASS            the requested relation was actually tested, and it held
    FAIL            an observed violation
    NOT_APPLICABLE  the test could not be instantiated
    ERROR           an observation or computation failed
    EXCLUDED        the caller explicitly excluded the invariant

No requested observation may silently disappear into PASS. In particular, a metric that could not
be compared -- a dict, a nested aggregate -- makes the outcome ERROR rather than PASS, because PASS
would claim the relation was tested for that metric when it was not.

`probe_async` is the real implementation. `probe` is a synchronous convenience wrapper and cannot
be used inside a running event loop.
"""

from __future__ import annotations

import asyncio
import traceback
from collections.abc import Mapping, Sequence

from inspect_ai.scorer import Metric, Scorer

from .case import Case
from .compare import (
    MetricChange,
    MetricComparison,
    compare_metric,
    compare_verdicts,
    divergent_metrics,
    in_negative_class,
)
from .contract import Contract, Invariant, Outcome
from .pipeline import (
    NonRepeatableBaseline,
    Observation,
    baseline_async,
    observe_async,
    resolve_metrics,
)
from .report import (
    DIVERGENT_METRICS,
    UNCOMPARED_METRICS,
    ProbeReport,
    ProbeResult,
    ReproductionScaffold,
)
from .transform import BUILTIN_TRANSFORMS, Transform
from .verify import verify_transformation


async def probe_async(
    scorer: Scorer,
    metrics: Sequence[Metric] | Mapping[str, Metric],
    cases: Sequence[Case],
    contract: Contract,
    *,
    transforms: Sequence[Transform] | None = None,
    repeatability_runs: int = 2,
    scorer_source: str | None = None,
) -> ProbeReport:
    """Probe a scoring pipeline against a declared contract.

    Args:
        scorer: the scorer under test. Must be offline and deterministic -- a PRECONDITION the
            package does not enforce; see `pipeline`'s module docstring.
        metrics: the metrics this pipeline reports, as a list or a {name: metric} mapping. A metric
            whose value is not a scalar cannot be compared, and its presence prevents a PASS.
        cases: the observations to score. More than one is required for any metric-layer finding.
        contract: what the caller asserts holds, and what the task rules out.
        transforms: extra transformations. Builtins are always included.
        repeatability_runs: how many times to observe the baseline before trusting it.
        scorer_source: an expression that rebuilds `scorer`, e.g. "my_scorer(pattern)". Supplying
            it lets the report emit runnable reproduction code; without it the report carries the
            reproduction data only.
    """
    if not cases:
        raise ValueError("cases must be non-empty")

    resolved = resolve_metrics(metrics)
    available = tuple(transforms or ()) + BUILTIN_TRANSFORMS

    def baseline_error(detail: str) -> ProbeReport:
        return ProbeReport(
            contract=contract,
            results=(
                ProbeResult(
                    invariant="-",
                    transformation="-",
                    outcome=Outcome.ERROR,
                    cases_total=len(cases),
                    details=(detail,),
                ),
            ),
        )

    try:
        base = await baseline_async(
            scorer, resolved, cases, repeatability_runs=repeatability_runs
        )
    except NonRepeatableBaseline as exc:
        return baseline_error(f"NONREPEATABLE_BASELINE: {exc}")
    except Exception as exc:  # noqa: BLE001 - see below
        # An unobservable baseline is an ERROR, not a crash escaping the public API. The
        # exception type, message and traceback tail are preserved in the detail so a genuine
        # programming error is still diagnosable rather than swallowed. This also makes the
        # baseline consistent with a scorer that raises on a TRANSFORMED observation, which
        # already produced a structured ERROR.
        tail = traceback.format_exc(limit=3).strip().splitlines()[-3:]
        return baseline_error(
            f"BASELINE_OBSERVATION_FAILED: {type(exc).__name__}: {exc}\n      "
            + "\n      ".join(line.strip() for line in tail)
        )

    results: list[ProbeResult] = []

    for invariant in contract.invariants:
        applicable = [t for t in available if t.valid_for(invariant)]
        if not applicable:
            results.append(
                ProbeResult(
                    invariant=invariant.name,
                    transformation="-",
                    outcome=Outcome.NOT_APPLICABLE,
                    cases_total=len(cases),
                    details=("no transformation declares that it tests this invariant",),
                )
            )
            continue
        for transformation in applicable:
            results.append(
                await _run_one(
                    scorer=scorer,
                    metrics=resolved,
                    cases=cases,
                    contract=contract,
                    invariant=invariant,
                    transformation=transformation,
                    base=base,
                    scorer_source=scorer_source,
                )
            )

    # excluded invariants are reported, not silently dropped, so the contract is visible
    for excluded in contract.exclusions:
        results.append(
            ProbeResult(
                invariant=excluded.name,
                transformation="-",
                outcome=Outcome.EXCLUDED,
                cases_total=len(cases),
                details=("the caller declared the task contract rules this out",),
            )
        )

    return ProbeReport(
        contract=contract,
        results=tuple(results),
        baseline_verdicts=base.verdicts,
        baseline_metrics=dict(base.metrics),
        baseline_notes=_baseline_notes(base),
    )


def probe(
    scorer: Scorer,
    metrics: Sequence[Metric] | Mapping[str, Metric],
    cases: Sequence[Case],
    contract: Contract,
    *,
    transforms: Sequence[Transform] | None = None,
    repeatability_runs: int = 2,
    scorer_source: str | None = None,
) -> ProbeReport:
    """Synchronous wrapper around `probe_async`. Not usable inside a running event loop."""
    from .pipeline import _require_no_running_loop

    _require_no_running_loop("probe")
    return asyncio.run(
        probe_async(
            scorer,
            metrics,
            cases,
            contract,
            transforms=transforms,
            repeatability_runs=repeatability_runs,
            scorer_source=scorer_source,
        )
    )


def _baseline_notes(base: Observation) -> tuple[str, ...]:
    """Flag a baseline that probably means the fixture, not the scorer, is wrong.

    Earned from a real mistake: a fixture whose completions did not match the scorer's anchored
    pattern produced an all-INCORRECT baseline, and the probe dutifully reported PASS -- it was
    comparing two equally broken observations. An all-wrong baseline is legitimate sometimes, so
    this is a note rather than an error, but it must be visible.
    """
    notes: list[str] = []
    negatives = [in_negative_class(v) for v in base.verdicts]
    if negatives and all(n is True for n in negatives):
        notes.append(
            f"all {len(negatives)} baseline verdicts are in the negative class; if that is "
            "unintended, the cases may not match what the scorer expects"
        )
    if len(set(map(repr, base.verdicts))) == 1 and len(base.verdicts) > 1:
        notes.append(f"every baseline verdict is identical ({base.verdicts[0]!r})")
    return tuple(notes)


async def _run_one(
    *,
    scorer: Scorer,
    metrics: Mapping[str, Metric],
    cases: Sequence[Case],
    contract: Contract,
    invariant: Invariant,
    transformation: Transform,
    base: Observation,
    scorer_source: str | None,
) -> ProbeResult:
    def result(outcome: Outcome, **kw: object) -> ProbeResult:
        return ProbeResult(
            invariant=invariant.name,
            transformation=transformation.name,
            outcome=outcome,
            cases_total=len(cases),
            **kw,  # type: ignore[arg-type]
        )

    # apply to the applicable subset; untransformed cases pass through so case count is preserved
    transformed: list[Case] = []
    changed_indices: list[int] = []
    for index, case in enumerate(cases):
        try:
            candidate = transformation.apply(case)
        except Exception as exc:  # noqa: BLE001 - a broken transform must not blame the scorer
            detail = (
                f"TRANSFORM_RAISED: {transformation.name} raised on case {index}: "
                f"{type(exc).__name__}: {exc}"
            )
            return result(Outcome.ERROR, details=(detail,))
        if candidate is None:
            transformed.append(case)
        else:
            transformed.append(candidate)
            changed_indices.append(index)

    if not changed_indices:
        return result(
            Outcome.NOT_APPLICABLE,
            details=("the transformation could not be expressed for any case",),
        )

    violation = verify_transformation(transformation, list(cases), transformed)
    if violation is not None:
        outcome = Outcome.ERROR if violation.is_error else Outcome.NOT_APPLICABLE
        prefix = (
            "TRANSFORM_CONTRACT_VIOLATED" if violation.is_error else violation.kind.value.upper()
        )
        return result(outcome, details=(f"{prefix}: {violation}",))

    try:
        after = await observe_async(scorer, metrics, transformed)
    except Exception as exc:  # noqa: BLE001 - an unobservable pipeline is ERROR, never FAIL
        return result(
            Outcome.ERROR,
            cases_transformed=len(changed_indices),
            details=(f"SCORER_RAISED: {type(exc).__name__}: {exc}",),
        )

    verdicts = tuple(
        compare_verdicts(invariant.relation, list(base.verdicts), list(after.verdicts))
    )
    metric_cmps: tuple[MetricComparison, ...] = tuple(
        compare_metric(name, base.metrics[name], after.metrics[name], contract.tolerance_for(name))
        for name in base.metrics
    )

    layers: list[str] = []
    if any(v.is_violation for v in verdicts):
        layers.append("scorer")
    if any(m.is_violation for m in metric_cmps):
        layers.append("metric")

    details: list[str] = []
    if layers == ["metric"] and divergent_metrics(list(metric_cmps)):
        details.append(
            f"{DIVERGENT_METRICS}: verdicts unchanged; "
            f"{sum(1 for m in metric_cmps if m.is_violation)} of "
            f"{len(metric_cmps)} metrics moved"
        )

    # A requested metric that could not be compared must not become a PASS. PASS means the
    # requested relation was tested and held; for a non-scalar metric it was never tested.
    uncompared = [m.name for m in metric_cmps if m.change is MetricChange.NOT_COMPARABLE]
    if uncompared:
        details.append(
            f"{UNCOMPARED_METRICS}: {sorted(uncompared)} are not scalar, so the relation was "
            "never tested for them. Pass only comparable metrics if you need a PASS."
        )

    if layers:
        outcome = Outcome.FAIL
    elif uncompared:
        outcome = Outcome.ERROR
    else:
        outcome = Outcome.PASS

    reproduction = None
    if outcome is Outcome.FAIL:
        reproduction = ReproductionScaffold(
            invariant=invariant.name,
            transformation=transformation.name,
            relation=invariant.relation,
            baseline_cases=tuple(cases),
            transformed_cases=tuple(transformed),
            verdicts_before=base.verdicts,
            verdicts_after=after.verdicts,
            metrics_before=dict(base.metrics),
            metrics_after=dict(after.metrics),
            changed_case_indices=tuple(changed_indices),
            scorer_source=scorer_source,
        )

    return result(
        outcome,
        layers=tuple(layers),
        cases_transformed=len(changed_indices),
        verdicts=verdicts,
        metrics=metric_cmps,
        details=tuple(details),
        reproduction=reproduction,
    )
