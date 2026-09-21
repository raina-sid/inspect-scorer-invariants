"""Arm 3: pipelines that are genuinely robust. These MUST return PASS.

This is the arm that measures whether the tool discriminates. An exclusion cell only shows the tool
obeys a contract; a robust cell shows it does not flag a scorer that is actually fine.

The strongest cell is novelty_bench under CUE_CASE. The SAME fixture fails MARKUP in arm 1 and
passes CUE_CASE here, because its partition function normalises case and whitespace and only misses
markup. A tool that condemned a scorer wholesale rather than per-invariant would fail that pair.
"""

from __future__ import annotations

from inspect_ai.scorer import accuracy, answer

from inspect_eval_probes import Contract, Outcome, probe
from inspect_eval_probes.invariants import CUE_CASE, CUE_WHITESPACE, WRONG_STAYS_INCORRECT

from .fixtures import (
    AGIEVAL_CASES,
    FRONTIERSCIENCE_CASES,
    NOVELTY_CASES,
    SCBENCH_WRONG_CASES,
    agieval_reduction,
    bold_one_generation,
    frontierscience_reduction,
    novelty_scorer_reduction,
    scbench_reduction,
    scbench_swap_letter,
    upper_one_generation,
)
from .test_contract_exclusions import CORE_CHOICE_CASES


def _result(report, invariant, transformation):
    for r in report.results:
        if r.invariant == invariant and r.transformation == transformation:
            return r
    raise AssertionError(f"no result for {invariant}/{transformation}:\n{report.render()}")


class TestAgievalWhitespaceTolerant:
    def test_passes(self):
        report = probe(
            agieval_reduction(),
            [accuracy()],
            AGIEVAL_CASES,
            Contract(invariants=(CUE_WHITESPACE,)),
        )
        assert _result(report, "CUE_WHITESPACE", "cue_space_removed").outcome is Outcome.PASS
        assert report.failures == (), report.render()


class TestFrontierscienceWhitespaceTolerant:
    def test_passes(self):
        # the same fixture whose MARKUP is excluded in arm 2 is genuinely robust to whitespace
        report = probe(
            frontierscience_reduction(),
            [accuracy()],
            FRONTIERSCIENCE_CASES,
            Contract(invariants=(CUE_WHITESPACE,)),
        )
        assert _result(report, "CUE_WHITESPACE", "cue_space_removed").outcome is Outcome.PASS
        assert report.failures == (), report.render()


class TestNoveltyBenchCaseTolerant:
    """THE discrimination cell: same fixture, MARKUP fails (arm 1) and CUE_CASE passes."""

    def test_passes(self):
        report = probe(
            novelty_scorer_reduction(),
            [accuracy()],
            NOVELTY_CASES,
            Contract(invariants=(CUE_CASE,)),
            transforms=[upper_one_generation()],
        )
        assert _result(report, "CUE_CASE", "upper_one_generation").outcome is Outcome.PASS
        assert report.failures == (), report.render()

    def test_the_same_fixture_fails_markup_and_passes_case(self):
        markup = probe(
            novelty_scorer_reduction(),
            [accuracy()],
            NOVELTY_CASES,
            Contract(invariants=(CUE_CASE,)),
            transforms=[bold_one_generation(), upper_one_generation()],
        )
        # bold_one_generation declares MARKUP, so it must NOT be used to judge CUE_CASE
        assert _result(markup, "CUE_CASE", "upper_one_generation").outcome is Outcome.PASS
        names = [r.transformation for r in markup.results]
        assert "bold_one_generation" not in names, (
            "a transformation that does not declare the invariant under test must not be applied"
        )


class TestScbenchWrongStaysWrong:
    def test_a_differently_wrong_answer_stays_wrong(self):
        report = probe(
            scbench_reduction(),
            [accuracy()],
            SCBENCH_WRONG_CASES,
            Contract(invariants=(WRONG_STAYS_INCORRECT,)),
            transforms=[scbench_swap_letter()],
        )
        r = _result(report, "WRONG_STAYS_INCORRECT", "scbench_swap_letter")
        assert r.outcome is Outcome.PASS
        assert report.failures == (), report.render()

    def test_the_baseline_was_genuinely_wrong_so_the_probe_had_something_to_preserve(self):
        report = probe(
            scbench_reduction(),
            [accuracy()],
            SCBENCH_WRONG_CASES,
            Contract(invariants=(WRONG_STAYS_INCORRECT,)),
            transforms=[scbench_swap_letter()],
        )
        # if the baseline had been correct the probe would be NOT_APPLICABLE, not PASS
        assert report.probes_executed == 1
        assert any("negative class" in n for n in report.baseline_notes)


class TestCoreChoiceWhitespaceAndCaseTolerant:
    def test_both_pass(self):
        report = probe(
            answer("letter"),
            [accuracy()],
            CORE_CHOICE_CASES,
            Contract(invariants=(CUE_WHITESPACE, CUE_CASE)),
        )
        assert _result(report, "CUE_WHITESPACE", "cue_space_removed").outcome is Outcome.PASS
        assert _result(report, "CUE_CASE", "cue_case_flip").outcome is Outcome.PASS
        assert report.failures == (), report.render()


class TestArmSummary:
    def test_no_robust_cell_produces_a_false_fail(self):
        cells = [
            ("agieval", agieval_reduction(), AGIEVAL_CASES,
             Contract(invariants=(CUE_WHITESPACE,)), None),
            ("frontierscience", frontierscience_reduction(), FRONTIERSCIENCE_CASES,
             Contract(invariants=(CUE_WHITESPACE,)), None),
            ("novelty_bench", novelty_scorer_reduction(), NOVELTY_CASES,
             Contract(invariants=(CUE_CASE,)), [upper_one_generation()]),
            ("scbench", scbench_reduction(), SCBENCH_WRONG_CASES,
             Contract(invariants=(WRONG_STAYS_INCORRECT,)), [scbench_swap_letter()]),
            ("core_choice", answer("letter"), CORE_CHOICE_CASES,
             Contract(invariants=(CUE_WHITESPACE, CUE_CASE)), None),
        ]
        for name, scorer_, cases, contract, transforms in cells:
            report = probe(scorer_, [accuracy()], cases, contract, transforms=transforms or [])
            assert report.failures == (), f"{name} produced a false FAIL:\n{report.render()}"
            assert report.probes_executed > 0, f"{name} observed nothing:\n{report.render()}"
