"""The scorecard's own tally must stay green, and the README quotes it.

If a cell drifts from its expected outcome this fails, which is the point: the package's claim is
the scorecard, so the scorecard failing must fail the build.
"""

from __future__ import annotations

from scorer_invariants import Outcome

from .summary import EXCLUSION, POSITIVE, ROBUST, cells, render


def test_every_cell_matches_its_expected_outcome():
    bad = [c for c in cells() if not c.ok]
    assert not bad, "\n".join(
        f"{c.eval_name}/{c.invariant}: expected {c.expected.name}, got {c.actual.name}"
        for c in bad
    )


def test_arm_sizes_are_what_the_readme_says():
    by_arm = {}
    for cell in cells():
        by_arm.setdefault(cell.arm, []).append(cell)
    assert len(by_arm[POSITIVE]) == 3
    assert len(by_arm[EXCLUSION]) == 3
    assert len(by_arm[ROBUST]) == 6
    assert sum(len(v) for v in by_arm.values()) == 12


def test_no_negative_cell_produces_a_false_fail():
    negatives = [c for c in cells() if c.arm != POSITIVE]
    assert len(negatives) == 9
    assert [c for c in negatives if c.actual is Outcome.FAIL] == []


def test_the_three_positives_are_three_distinct_invariants():
    positives = [c for c in cells() if c.arm == POSITIVE]
    assert len({c.invariant for c in positives}) == 3


def test_rendered_text_carries_the_claim_discipline():
    text = render()
    assert "validation fixture set, not an estimate" in text
    assert "Not a recall estimate" in text
    # the word "precision" must not appear: it is not what 12 hand-picked cells measure
    assert "precision" not in text.lower()
