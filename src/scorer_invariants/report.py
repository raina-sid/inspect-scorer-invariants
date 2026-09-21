"""Results, and how they are reported.

The fields here are the ones needed to adjudicate a finding. Three of the five questions that
matter can be answered mechanically -- which invariant, what moved, how to reproduce it. Two
cannot, and the report does not pretend otherwise:

    is this a real defect or contract-excluded?   the caller's judgment, recorded not adjudicated
    do the author's existing tests cover it?      outside this package entirely
"""

from __future__ import annotations

import textwrap
import warnings
from dataclasses import dataclass, field
from typing import Any

from .case import Case
from .compare import MetricComparison, VerdictComparison
from .contract import Contract, Outcome, Relation

#: Reported when the scorer layer is clean but some, not all, metrics moved. On the worldsense
#: fixture this is the only thing separating a silent 1.0 -> 0.0 from a legitimate score of zero.
DIVERGENT_METRICS = "DIVERGENT_METRICS"

#: Reported when a requested metric could not be compared at all (a dict, a nested aggregate).
#: Its presence prevents a PASS: PASS means the requested relation was tested and held, and for an
#: uncomparable metric it was never tested.
UNCOMPARED_METRICS = "UNCOMPARED_METRICS"


@dataclass(frozen=True)
class Reproduction:
    """Everything needed to re-observe a result.

    Structured data is always present. Executable code is emitted ONLY when the caller supplied
    the scorer in a reconstructible form (`scorer_source`), because arbitrary scorer source cannot
    be regenerated -- claiming otherwise would be a lie told by a tool whose whole point is not
    lying about measurement.
    """

    invariant: str
    transformation: str
    relation: Relation
    #: the WHOLE case list, both sides. A metric-layer finding cannot be reproduced from a single
    #: case -- an aggregate only moves once every case has been scored -- so carrying just the
    #: first changed pair would emit a snippet that does not reproduce what the report claims.
    baseline_cases: tuple[Case, ...]
    transformed_cases: tuple[Case, ...]
    verdicts_before: tuple[Any, ...]
    verdicts_after: tuple[Any, ...]
    metrics_before: dict[str, Any]
    metrics_after: dict[str, Any]
    changed_case_indices: tuple[int, ...] = ()
    scorer_source: str | None = None

    @property
    def code(self) -> str | None:
        """A runnable snippet, or None when the scorer is not reconstructible."""
        if self.scorer_source is None:
            return None
        metric_names = ", ".join(repr(n) for n in self.metrics_before)
        before = ",\n    ".join(repr(c) for c in self.baseline_cases)
        after = ",\n    ".join(repr(c) for c in self.transformed_cases)
        return textwrap.dedent(
            f"""\
            # {self.invariant} / {self.transformation}
            # cases changed: {list(self.changed_case_indices)} of {len(self.baseline_cases)}
            from scorer_invariants import Case
            from scorer_invariants.pipeline import observe, resolve_metrics

            scorer = {self.scorer_source}
            # supply the metrics this pipeline reports, named: {metric_names}
            metrics = resolve_metrics([...])

            before = [
                {before},
            ]
            after = [
                {after},
            ]

            b = observe(scorer, metrics, before)
            a = observe(scorer, metrics, after)
            print(b.verdicts)      # {self.verdicts_before!r}
            print(a.verdicts)      # {self.verdicts_after!r}
            print(dict(b.metrics)) # {self.metrics_before!r}
            print(dict(a.metrics)) # {self.metrics_after!r}
            """
        )


@dataclass(frozen=True)
class ProbeResult:
    invariant: str
    transformation: str
    outcome: Outcome
    #: which layer(s) the violation was found at: "scorer", "metric", or both
    layers: tuple[str, ...] = ()
    cases_total: int = 0
    #: how many cases the transformation actually rewrote. There is deliberately no separate
    #: "applicable" count: a case is applicable exactly when `apply` returned a new Case, so a
    #: second field would be the same number under a different name.
    cases_transformed: int = 0
    verdicts: tuple[VerdictComparison, ...] = ()
    metrics: tuple[MetricComparison, ...] = ()
    details: tuple[str, ...] = ()
    reproduction: Reproduction | None = None

    @property
    def executed(self) -> bool:
        """Did this probe actually observe anything? Only PASS and FAIL count."""
        return self.outcome in (Outcome.PASS, Outcome.FAIL)

    @property
    def label(self) -> str:
        if self.outcome is Outcome.FAIL and self.layers:
            return f"FAIL [{'+'.join(layer.upper() for layer in self.layers)}]"
        return self.outcome.name


@dataclass(frozen=True)
class ProbeReport:
    contract: Contract
    results: tuple[ProbeResult, ...]
    baseline_verdicts: tuple[Any, ...] = ()
    baseline_metrics: dict[str, Any] = field(default_factory=dict)
    #: Notes about the baseline itself, e.g. that every verdict is already wrong. Not failures --
    #: a legitimately all-incorrect baseline exists -- but a probe against a broken pipeline
    #: measures nothing, and that must be visible rather than inferred.
    baseline_notes: tuple[str, ...] = ()

    @property
    def contract_hash(self) -> str:
        return self.contract.hash()

    @property
    def probes_executed(self) -> int:
        return sum(1 for r in self.results if r.executed)

    @property
    def failures(self) -> tuple[ProbeResult, ...]:
        return tuple(r for r in self.results if r.outcome is Outcome.FAIL)

    @property
    def errors(self) -> tuple[ProbeResult, ...]:
        return tuple(r for r in self.results if r.outcome is Outcome.ERROR)

    def outcome_counts(self) -> dict[str, int]:
        counts = {o.name: 0 for o in Outcome}
        for r in self.results:
            counts[r.outcome.name] += 1
        return counts

    def render(self) -> str:
        """Grid first, then detail for FAILs only.

        Grid-first is not a style choice -- it is the format that made 18 evals legible during the
        pre-registered run, where most cells are not failures.
        """
        lines: list[str] = []
        inv = ", ".join(i.name for i in self.contract.invariants)
        exc = ", ".join(e.name for e in self.contract.exclusions) or "-"
        lines.append(f"contract {self.contract_hash[:12]}")
        lines.append(f"  invariants: {inv}")
        lines.append(f"  exclusions: {exc}")
        for note in self.baseline_notes:
            lines.append(f"  ! baseline: {note}")
        lines.append("")

        width_i = max((len(r.invariant) for r in self.results), default=9)
        width_t = max((len(r.transformation) for r in self.results), default=14)
        for r in self.results:
            cases = f"  {r.cases_transformed}/{r.cases_total} transformed" if r.executed else ""
            lines.append(
                f"  {r.invariant:<{width_i}}  {r.transformation:<{width_t}}  {r.label}{cases}"
            )

        counts = self.outcome_counts()
        lines.append("")
        lines.append(
            f"  {self.probes_executed} executed | "
            + " | ".join(f"{name} {counts[name]}" for name in ("PASS", "FAIL", "ERROR", "NOT_APPLICABLE", "EXCLUDED"))
        )

        # one loop covers both: an ERROR result carries no verdicts or metrics, so those
        # sections skip themselves rather than needing a second near-identical loop
        for r in self.failures + self.errors:
            lines.append("")
            lines.append(f"  --- {r.invariant} / {r.transformation}  {r.label}")
            moved = [v for v in r.verdicts if v.is_violation]
            if moved:
                lines.append("      Score:")
                lines += [
                    f"        case {v.case_index}: {v.before!r} -> {v.after!r}  [{v.change.value}]"
                    for v in moved[:5]
                ]
                if len(moved) > 5:
                    lines.append(f"        ... and {len(moved) - 5} more")
            if r.metrics:
                lines.append("      Metrics:")
                lines += [
                    f"        {m}  {'FAIL' if m.is_violation else 'ok'}" for m in r.metrics
                ]
            lines += [f"      {detail}" for detail in r.details]

        return "\n".join(lines)

    def __str__(self) -> str:
        return self.render()


class InvariantViolation(AssertionError):
    """Raised by `assert_invariants` when a declared invariant did not hold."""


def assert_invariants(report: ProbeReport, *, warn_on_error: bool = True) -> None:
    """Fail a test when a declared invariant was violated.

    EXCLUDED and NOT_APPLICABLE do not fail. ERROR does not fail either -- an observation that
    could not be made is not evidence of a defect -- but it warns, because a scorer that could not
    be probed must never read as green.

    Zero executed probes IS a failure. A contract whose every probe came back NOT_APPLICABLE would
    otherwise stay green forever, which is the vacuous-metric failure mode: a check that looks
    fine because nothing ever fired.
    """
    if report.probes_executed == 0:
        raise InvariantViolation(
            "no probe was executed: every result was EXCLUDED, NOT_APPLICABLE or ERROR, so this "
            "assertion would pass without observing anything.\n\n" + report.render()
        )

    if warn_on_error and report.errors:
        names = ", ".join(f"{r.invariant}/{r.transformation}" for r in report.errors)
        warnings.warn(
            f"{len(report.errors)} probe(s) could not be observed and are NOT passes: {names}",
            stacklevel=2,
        )

    if report.failures:
        raise InvariantViolation(
            f"{len(report.failures)} declared invariant(s) violated:\n\n" + report.render()
        )
