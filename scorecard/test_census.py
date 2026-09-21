"""The census must stay internally consistent and must not quietly flatter itself."""

from __future__ import annotations

from .census import CENSUS, Reach, counts, summary


def test_counts_sum_to_the_census_size():
    assert sum(counts().values()) == len(CENSUS) == 18


def test_every_entry_has_a_reason():
    for entry in CENSUS:
        assert entry.note, entry.eval_name


def test_no_duplicate_evals():
    names = [e.eval_name for e in CENSUS]
    assert len(names) == len(set(names))


def test_the_measured_breakdown():
    # pinned so a later edit cannot drift the coverage claim without a test change
    tally = counts()
    assert tally[Reach.EXERCISABLE.value] == 9
    assert tally[Reach.BLOCKED_JUDGE.value] == 4
    assert tally[Reach.BLOCKED_SANDBOX.value] == 1
    assert tally[Reach.BLOCKED_UPSTREAM.value] == 2
    assert tally[Reach.NO_SURFACE.value] == 2


def test_at_most_half_were_exercisable_and_the_summary_says_so():
    # exactly half, as measured. An earlier version of this test asserted "fewer than half",
    # which was false -- 9 of 18. Stating a coverage claim more pessimistic than the data is
    # still stating something the data does not support.
    tally = counts()
    assert tally[Reach.EXERCISABLE.value] == len(CENSUS) // 2
    text = summary()
    assert "exercisable: 9/18" in text
    assert "Not a recall estimate" in text
