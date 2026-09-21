"""Arm 2: real strictness that the task contract licenses. These MUST NOT be reported as FAIL.

Each of these produces a large, reproducible verdict change. None is a defect, because the eval's
own prompt or its own tests rule the invariant out. Without this arm the package is a
false-positive generator, so this is the arm that matters most for whether anyone should trust it.

A NOTE ON THE COUNT. The design listed five exclusion cells: frontierscience, gpqa, hellaswag,
truthfulqa and scbench. But gpqa, hellaswag and truthfulqa all fail markup through the SAME core
mechanism -- `parse_answers`' character class in inspect_ai core -- so listing them separately
would be three cells testing one thing. They are collapsed into a single `core_choice` cell here.
That reduces the negative count from 9 to 7, which is the honest number.
"""

from __future__ import annotations

from inspect_ai.scorer import accuracy, answer

from scorer_invariants import Case, Contract, Outcome, probe
from scorer_invariants.invariants import CUE_CASE, CUE_WHITESPACE, MARKUP

from .fixtures import (
    FRONTIERSCIENCE_CASES,
    SCBENCH_CASES,
    frontierscience_reduction,
    scbench_reduction,
)

CORE_CHOICE_CASES = [
    Case(completion="Reasoning.\nANSWER: B", target="B"),
    Case(completion="Reasoning.\nANSWER: C", target="C"),
]


def _outcomes(report, invariant):
    return [r.outcome for r in report.results if r.invariant == invariant]


class TestFrontierscienceMarkupExcluded:
    """'VERDICT: **8**' scores 0 instead of 0.8 -- an 8-point swing that is NOT a defect."""

    def test_excluded_when_the_contract_says_so(self):
        report = probe(
            frontierscience_reduction(),
            [accuracy()],
            FRONTIERSCIENCE_CASES,
            Contract(invariants=(CUE_WHITESPACE,), exclusions=(MARKUP,)),
        )
        assert _outcomes(report, "MARKUP") == [Outcome.EXCLUDED]
        assert report.failures == (), report.render()

    def test_the_underlying_change_is_real_which_is_why_exclusion_matters(self):
        # if the caller wrongly asserts MARKUP, the tool DOES report it. The exclusion is doing
        # work, not hiding an absence -- otherwise this arm would prove nothing.
        report = probe(
            frontierscience_reduction(),
            [accuracy()],
            FRONTIERSCIENCE_CASES,
            Contract(invariants=(MARKUP,)),
        )
        assert report.failures, "the swing is real; only the contract makes it acceptable"


class TestCoreChoiceMarkupExcluded:
    """Core answer('letter') rejects 'ANSWER: **B**'. A core property, out of scope."""

    def test_excluded(self):
        report = probe(
            answer("letter"),
            [accuracy()],
            CORE_CHOICE_CASES,
            Contract(invariants=(CUE_WHITESPACE, CUE_CASE), exclusions=(MARKUP,)),
        )
        assert _outcomes(report, "MARKUP") == [Outcome.EXCLUDED]
        assert report.failures == (), report.render()

    def test_the_change_is_real_and_lives_in_core_not_in_any_eval(self):
        report = probe(
            answer("letter"), [accuracy()], CORE_CHOICE_CASES, Contract(invariants=(MARKUP,))
        )
        assert report.failures
        # three evals (gpqa, hellaswag, truthfulqa) inherit this from one core char class, which
        # is why they collapse to a single cell rather than three
        assert report.failures[0].invariant == "MARKUP"


class TestScbenchMarkupExcluded:
    """The answer is JSON inside a mandated 'Return EXACTLY' block."""

    def test_excluded(self):
        report = probe(
            scbench_reduction(),
            [accuracy()],
            SCBENCH_CASES,
            Contract(invariants=(CUE_WHITESPACE,), exclusions=(MARKUP,)),
        )
        assert _outcomes(report, "MARKUP") == [Outcome.EXCLUDED]
        assert report.failures == (), report.render()


class TestArmSummary:
    def test_no_exclusion_cell_produces_a_false_fail(self):
        cells = [
            (
                "frontierscience",
                frontierscience_reduction(),
                FRONTIERSCIENCE_CASES,
                Contract(invariants=(CUE_WHITESPACE,), exclusions=(MARKUP,)),
            ),
            (
                "core_choice",
                answer("letter"),
                CORE_CHOICE_CASES,
                Contract(invariants=(CUE_WHITESPACE, CUE_CASE), exclusions=(MARKUP,)),
            ),
            (
                "scbench",
                scbench_reduction(),
                SCBENCH_CASES,
                Contract(invariants=(CUE_WHITESPACE,), exclusions=(MARKUP,)),
            ),
        ]
        for name, scorer_, cases, contract in cells:
            report = probe(scorer_, [accuracy()], cases, contract)
            assert report.failures == (), f"{name} produced a false FAIL:\n{report.render()}"

    def test_exclusion_is_visible_in_the_report_not_silent(self):
        report = probe(
            frontierscience_reduction(),
            [accuracy()],
            FRONTIERSCIENCE_CASES,
            Contract(invariants=(CUE_WHITESPACE,), exclusions=(MARKUP,)),
        )
        assert "EXCLUDED" in report.render()
        assert "MARKUP" in report.render()
