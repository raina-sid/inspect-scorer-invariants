from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from inspect_eval_probes.contract import (
    Contract,
    Invariant,
    Outcome,
    Relation,
    Tolerance,
)
from inspect_eval_probes.invariants import (
    ALL_INVARIANTS,
    CUE_CASE,
    CUE_WHITESPACE,
    MARKUP,
    WRONG_STAYS_INCORRECT,
    by_name,
)


class TestContractValidation:
    def test_empty_invariants_rejected(self):
        # the whole point of the package is that the caller states a contract
        with pytest.raises(ValueError, match="non-empty"):
            Contract(invariants=())

    def test_invariant_cannot_be_both_asserted_and_excluded(self):
        with pytest.raises(ValueError, match="both asserted and excluded"):
            Contract(invariants=(CUE_CASE,), exclusions=(CUE_CASE,))

    def test_duplicate_invariants_rejected(self):
        with pytest.raises(ValueError, match="duplicate entries in invariants"):
            Contract(invariants=(CUE_CASE, CUE_CASE))

    def test_duplicate_exclusions_rejected(self):
        with pytest.raises(ValueError, match="duplicate entries in exclusions"):
            Contract(invariants=(CUE_CASE,), exclusions=(MARKUP, MARKUP))

    def test_lists_are_normalised_to_tuples(self):
        c = Contract(invariants=[CUE_CASE, MARKUP])
        assert isinstance(c.invariants, tuple)
        assert isinstance(c.exclusions, tuple)

    def test_is_immutable(self):
        c = Contract(invariants=(CUE_CASE,))
        with pytest.raises(FrozenInstanceError):
            c.invariants = ()  # type: ignore[misc]


class TestContractQueries:
    def test_asserts_and_excludes(self):
        c = Contract(invariants=(CUE_CASE,), exclusions=(MARKUP,))
        assert c.asserts(CUE_CASE)
        assert not c.asserts(MARKUP)
        assert c.excludes(MARKUP)
        assert not c.excludes(CUE_CASE)

    def test_tolerance_lookup_defaults_to_none(self):
        c = Contract(invariants=(CUE_CASE,), tolerances={"accuracy": Tolerance(absolute=0.01)})
        assert c.tolerance_for("accuracy") == Tolerance(absolute=0.01)
        assert c.tolerance_for("ws_accuracy") is None


class TestContractHash:
    def test_order_does_not_change_the_hash(self):
        a = Contract(invariants=(CUE_CASE, CUE_WHITESPACE))
        b = Contract(invariants=(CUE_WHITESPACE, CUE_CASE))
        assert a.hash() == b.hash()

    def test_moving_an_invariant_to_exclusions_changes_the_hash(self):
        # this is the integrity property: silencing a FAIL by excluding the invariant
        # cannot be done without the recorded hash changing
        asserted = Contract(invariants=(CUE_CASE, MARKUP))
        silenced = Contract(invariants=(CUE_CASE,), exclusions=(MARKUP,))
        assert asserted.hash() != silenced.hash()

    def test_tolerance_is_folded_into_the_hash(self):
        strict = Contract(invariants=(CUE_CASE,))
        loose = Contract(invariants=(CUE_CASE,), tolerances={"accuracy": Tolerance(absolute=0.5)})
        assert strict.hash() != loose.hash()

    def test_tolerance_value_changes_the_hash(self):
        a = Contract(invariants=(CUE_CASE,), tolerances={"m": Tolerance(absolute=0.1)})
        b = Contract(invariants=(CUE_CASE,), tolerances={"m": Tolerance(absolute=0.2)})
        assert a.hash() != b.hash()

    def test_hash_is_stable_across_processes(self):
        # sha256 over canonical json, not python's salted hash()
        c = Contract(invariants=(CUE_CASE,))
        assert c.hash() == Contract(invariants=(CUE_CASE,)).hash()
        assert len(c.hash()) == 64


class TestSerialisation:
    def test_round_trips_through_names(self):
        c = Contract(invariants=(CUE_CASE, MARKUP), exclusions=(CUE_WHITESPACE,))
        d = c.to_dict()
        rebuilt = Contract(
            invariants=tuple(by_name(i["name"]) for i in d["invariants"]),
            exclusions=tuple(by_name(e["name"]) for e in d["exclusions"]),
        )
        assert rebuilt.hash() == c.hash()

    def test_serialisation_records_the_relation(self):
        d = Contract(invariants=(WRONG_STAYS_INCORRECT,)).to_dict()
        assert d["invariants"][0]["relation"] == "stays_incorrect"


class TestTolerance:
    def test_negative_tolerance_rejected(self):
        with pytest.raises(ValueError, match="non-negative"):
            Tolerance(absolute=-0.1)
        with pytest.raises(ValueError, match="non-negative"):
            Tolerance(relative=-0.1)

    def test_default_permits_nothing(self):
        t = Tolerance()
        assert t.permits(1.0, 1.0)
        assert not t.permits(1.0, 1.0000001)

    def test_absolute(self):
        t = Tolerance(absolute=0.05)
        assert t.permits(1.0, 1.04)
        assert not t.permits(1.0, 1.06)

    def test_relative(self):
        t = Tolerance(relative=0.10)
        assert t.permits(100.0, 109.0)
        assert not t.permits(100.0, 111.0)

    def test_relative_against_a_zero_baseline_permits_only_exact(self):
        # 0 * anything is 0, so a relative tolerance cannot rescue a move away from zero
        t = Tolerance(relative=0.5)
        assert t.permits(0.0, 0.0)
        assert not t.permits(0.0, 0.1)


class TestInvariantRegistry:
    def test_five_invariants_ship(self):
        assert len(ALL_INVARIANTS) == 5

    def test_the_two_rejected_families_are_absent(self):
        # measured at zero findings across 18 evals; shipping them would claim
        # coverage we did not observe
        names = {i.name for i in ALL_INVARIANTS}
        assert "NUMERIC_EQUIVALENT" not in names
        assert "LEGITIMATE_DISTRACTOR" not in names

    def test_exactly_one_invariant_is_not_equality(self):
        non_equal = [i for i in ALL_INVARIANTS if i.relation is not Relation.EQUAL]
        assert non_equal == [WRONG_STAYS_INCORRECT]

    def test_every_invariant_has_a_description(self):
        for inv in ALL_INVARIANTS:
            assert len(inv.description) > 40, inv.name

    def test_by_name_rejects_unknown(self):
        with pytest.raises(KeyError, match="unknown invariant"):
            by_name("NUMERIC_EQUIVALENT")

    def test_invariants_are_hashable_and_usable_in_sets(self):
        # Transform.tests is a set of invariants, so this has to hold
        assert len({CUE_CASE, CUE_CASE, MARKUP}) == 2


class TestOutcome:
    def test_five_outcomes(self):
        assert {o.name for o in Outcome} == {
            "PASS",
            "FAIL",
            "NOT_APPLICABLE",
            "ERROR",
            "EXCLUDED",
        }


def test_custom_invariant_is_allowed_but_not_in_the_registry():
    # callers may define their own; the registry is only what ships
    mine = Invariant(name="MY_THING", relation=Relation.EQUAL, description="x" * 50)
    c = Contract(invariants=(mine,))
    assert c.asserts(mine)
    with pytest.raises(KeyError):
        by_name("MY_THING")
