"""Run every scorecard cell and report the tally.

The README quotes this script's output rather than a number counted by hand. Counting cells in prose
is how a document ends up claiming two different totals -- which is exactly what happened while this
package was being written, before this file existed.

    python -m scorecard.summary
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from inspect_ai.scorer import accuracy, answer

from inspect_scorer_probes import Case, Contract, Outcome, ProbeReport, probe
from inspect_scorer_probes.invariants import (
    CUE_CASE,
    CUE_WHITESPACE,
    MARKUP,
    WRONG_STAYS_INCORRECT,
)

from .census import summary as census_summary
from .fixtures import (
    AGIEVAL_CASES,
    FRONTIERSCIENCE_CASES,
    NOVELTY_CASES,
    SCBENCH_CASES,
    SCBENCH_WRONG_CASES,
    TAU2_CASES,
    WORLDSENSE_CASES,
    agieval_reduction,
    bold_one_generation,
    communicated_info_reduction,
    differently_wrong_error_code,
    frontierscience_reduction,
    novelty_scorer_reduction,
    scbench_reduction,
    scbench_swap_letter,
    upper_one_generation,
    worldsense_scorer_reduction,
    ws_accuracy_reduction,
)

CORE_CHOICE_CASES = [
    Case(completion="Reasoning.\nANSWER: B", target="B"),
    Case(completion="Reasoning.\nANSWER: C", target="C"),
]

POSITIVE = "positive defect"
EXCLUSION = "contract exclusion"
ROBUST = "genuinely robust"


@dataclass
class Cell:
    arm: str
    eval_name: str
    invariant: str
    expected: Outcome
    report: ProbeReport

    @property
    def actual(self) -> Outcome:
        """The outcome for this cell's invariant.

        A cell is defined by (eval, invariant). Several transformations can test one invariant, so
        the cell takes the most severe outcome among them: a FAIL anywhere means the invariant did
        not hold.
        """
        severity = [
            Outcome.FAIL,
            Outcome.ERROR,
            Outcome.PASS,
            Outcome.NOT_APPLICABLE,
            Outcome.EXCLUDED,
        ]
        outcomes = [r.outcome for r in self.report.results if r.invariant == self.invariant]
        if not outcomes:
            raise AssertionError(f"no result for {self.eval_name}/{self.invariant}")
        for candidate in severity:
            if candidate in outcomes:
                return candidate
        raise AssertionError("unreachable")

    @property
    def ok(self) -> bool:
        return self.actual is self.expected


def _probe(scorer_: Any, metrics: Any, cases: Any, contract: Contract, transforms: Any = None):
    return probe(scorer_, metrics, cases, contract, transforms=transforms or [])


def cells() -> list[Cell]:
    out: list[Cell] = []

    # ---- arm 1: three real scoring defects, on three different scorer types. Two of the three are
    # inherited from their upstream reference implementations rather than being the port's own bugs --
    # see fixtures.PROVENANCE. Irrelevant to detection, which is what this arm measures.
    out.append(
        Cell(
            POSITIVE, "worldsense", "CUE_CASE", Outcome.FAIL,
            _probe(
                worldsense_scorer_reduction(),
                {"accuracy": accuracy(), "ws_accuracy": ws_accuracy_reduction()},
                WORLDSENSE_CASES,
                Contract(invariants=(CUE_CASE,)),
            ),
        )
    )
    out.append(
        Cell(
            POSITIVE, "novelty_bench", "MARKUP", Outcome.FAIL,
            _probe(
                novelty_scorer_reduction(), [accuracy()], NOVELTY_CASES,
                Contract(invariants=(MARKUP,)), [bold_one_generation()],
            ),
        )
    )
    out.append(
        Cell(
            POSITIVE, "tau2", "WRONG_STAYS_INCORRECT", Outcome.FAIL,
            _probe(
                communicated_info_reduction(), [accuracy()], TAU2_CASES,
                Contract(invariants=(WRONG_STAYS_INCORRECT,)), [differently_wrong_error_code()],
            ),
        )
    )

    # ---- arm 2: real strictness the task contract licenses
    exclusion_specs = [
        ("frontierscience", frontierscience_reduction(), FRONTIERSCIENCE_CASES,
         Contract(invariants=(CUE_WHITESPACE,), exclusions=(MARKUP,))),
        ("core_choice", answer("letter"), CORE_CHOICE_CASES,
         Contract(invariants=(CUE_WHITESPACE, CUE_CASE), exclusions=(MARKUP,))),
        ("scbench", scbench_reduction(), SCBENCH_CASES,
         Contract(invariants=(CUE_WHITESPACE,), exclusions=(MARKUP,))),
    ]
    for name, scorer_, cases_, contract_ in exclusion_specs:
        out.append(
            Cell(EXCLUSION, name, "MARKUP", Outcome.EXCLUDED,
                 _probe(scorer_, [accuracy()], cases_, contract_))
        )

    # ---- arm 3: pipelines that are actually fine
    robust_specs = [
        ("agieval", "CUE_WHITESPACE", agieval_reduction(), AGIEVAL_CASES,
         Contract(invariants=(CUE_WHITESPACE,)), None),
        ("frontierscience", "CUE_WHITESPACE", frontierscience_reduction(), FRONTIERSCIENCE_CASES,
         Contract(invariants=(CUE_WHITESPACE,)), None),
        ("novelty_bench", "CUE_CASE", novelty_scorer_reduction(), NOVELTY_CASES,
         Contract(invariants=(CUE_CASE,)), [upper_one_generation()]),
        ("scbench", "WRONG_STAYS_INCORRECT", scbench_reduction(), SCBENCH_WRONG_CASES,
         Contract(invariants=(WRONG_STAYS_INCORRECT,)), [scbench_swap_letter()]),
        ("core_choice", "CUE_WHITESPACE", answer("letter"), CORE_CHOICE_CASES,
         Contract(invariants=(CUE_WHITESPACE, CUE_CASE)), None),
        ("core_choice", "CUE_CASE", answer("letter"), CORE_CHOICE_CASES,
         Contract(invariants=(CUE_WHITESPACE, CUE_CASE)), None),
    ]
    for name, invariant, scorer_, cases_, contract_, transforms_ in robust_specs:
        out.append(
            Cell(ROBUST, name, invariant, Outcome.PASS,
                 _probe(scorer_, [accuracy()], cases_, contract_, transforms_))
        )

    return out


def render() -> str:
    all_cells = cells()
    lines = ["Scorecard", ""]
    for arm in (POSITIVE, EXCLUSION, ROBUST):
        arm_cells = [c for c in all_cells if c.arm == arm]
        lines.append(f"  {arm} ({len(arm_cells)} cells)")
        for cell in arm_cells:
            mark = "ok " if cell.ok else "XX "
            lines.append(
                f"    {mark}{cell.eval_name:<16} {cell.invariant:<22} "
                f"{cell.actual.name:<15} expected {cell.expected.name}"
            )
        lines.append("")

    positives = [c for c in all_cells if c.arm == POSITIVE]
    negatives = [c for c in all_cells if c.arm != POSITIVE]
    false_fails = [c for c in negatives if c.actual is Outcome.FAIL]
    lines.append(
        f"  {sum(c.ok for c in positives)}/{len(positives)} positive fixtures FAILed as expected"
    )
    lines.append(
        f"  {len(false_fails)}/{len(negatives)} negative fixtures produced a false FAIL"
    )
    lines.append(f"  {len(all_cells)} cells total")
    lines.append("")
    lines.append("  This is a validation fixture set, not an estimate of detector accuracy.")
    lines.append("")
    lines.append(census_summary())
    return "\n".join(lines)


if __name__ == "__main__":
    print(render())
