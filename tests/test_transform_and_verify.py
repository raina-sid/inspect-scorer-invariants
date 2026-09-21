"""Tests for the transformation contract and its runtime enforcement.

The important ones are in TestBadTransformations: the framework must blame a broken
transformation, never the scorer.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from scorer_invariants.case import FIELDS, Case, changed_fields
from scorer_invariants.invariants import CUE_CASE, CUE_WHITESPACE, MARKUP
from scorer_invariants.transform import (
    ANSWER_BOLDED,
    BUILTIN_TRANSFORMS,
    CUE_CASE_FLIP,
    CUE_SPACE_REMOVED,
    Transform,
    transform,
    transforms_for,
)
from scorer_invariants.verify import ViolationKind, verify_transformation


def case(completion="ANSWER: TRUE", target="TRUE", **kw):
    return Case(completion=completion, target=target, **kw)


class TestCase:
    def test_is_frozen(self):
        with pytest.raises(FrozenInstanceError):
            case().completion = "x"  # type: ignore[misc]

    def test_unknown_field_rejected(self):
        with pytest.raises(KeyError, match="unknown Case field"):
            case().field("nope")

    def test_changed_fields_detects_in_place_metadata_edits(self):
        # Case is frozen but the dict is not, so equality comparison is what protects us
        before = case(metadata={"k": 1})
        after = case(metadata={"k": 2})
        assert changed_fields(before, after) == {"metadata"}


class TestTransformDeclaration:
    def test_helper_derives_holds_fixed(self):
        t = transform("t", [CUE_CASE], ["completion"], lambda c: c)
        assert t.mutates == {"completion"}
        assert t.holds_fixed == (FIELDS - {"completion"}) | {"case_count"}

    def test_empty_tests_rejected(self):
        with pytest.raises(ValueError, match="at least one invariant"):
            transform("t", [], ["completion"], lambda c: c)

    def test_empty_mutates_rejected(self):
        # a transformation that changes nothing yields a guaranteed PASS
        with pytest.raises(ValueError, match="vacuous PASS"):
            transform("t", [CUE_CASE], [], lambda c: c)

    def test_mutates_must_name_case_fields(self):
        with pytest.raises(ValueError, match="non-Case fields"):
            transform("t", [CUE_CASE], ["banana"], lambda c: c)

    def test_contradictory_declaration_rejected(self):
        with pytest.raises(ValueError, match="both\n?.*mutated and held fixed|contradictory"):
            Transform(
                name="t",
                tests=frozenset({CUE_CASE}),
                mutates=frozenset({"completion"}),
                holds_fixed=frozenset({"completion", "target", "metadata", "messages", "case_count"}),
                apply=lambda c: c,
            )

    def test_incomplete_declaration_rejected(self):
        with pytest.raises(ValueError, match="incomplete declaration"):
            Transform(
                name="t",
                tests=frozenset({CUE_CASE}),
                mutates=frozenset({"completion"}),
                holds_fixed=frozenset({"case_count"}),  # target/metadata/messages unaccounted
                apply=lambda c: c,
            )

    def test_case_count_must_be_held_fixed(self):
        with pytest.raises(ValueError, match="hold case_count fixed"):
            Transform(
                name="t",
                tests=frozenset({CUE_CASE}),
                mutates=frozenset({"completion"}),
                holds_fixed=FIELDS - {"completion"},
                apply=lambda c: c,
            )

    def test_valid_for_matches_only_declared_invariants(self):
        assert CUE_CASE_FLIP.valid_for(CUE_CASE)
        assert not CUE_CASE_FLIP.valid_for(MARKUP)

    def test_transforms_for_selects_by_declaration(self):
        assert CUE_CASE_FLIP in transforms_for(CUE_CASE)
        assert ANSWER_BOLDED in transforms_for(MARKUP)
        assert CUE_SPACE_REMOVED in transforms_for(CUE_WHITESPACE)
        assert ANSWER_BOLDED not in transforms_for(CUE_CASE)

    def test_every_builtin_declares_a_complete_contract(self):
        for t in BUILTIN_TRANSFORMS:
            assert t.mutates
            assert "case_count" in t.holds_fixed
            assert not (t.mutates & t.holds_fixed)
            assert FIELDS - t.mutates - t.holds_fixed == set()


class TestBuiltinRewrites:
    def test_cue_case_flip(self):
        out = CUE_CASE_FLIP.apply(case("ANSWER: TRUE"))
        assert out is not None
        assert out.completion == "Answer: True"

    def test_cue_case_flip_not_applicable_without_caps(self):
        assert CUE_CASE_FLIP.apply(case("answer: true")) is None

    def test_cue_space_removed(self):
        out = CUE_SPACE_REMOVED.apply(case("ANSWER: B"))
        assert out is not None
        assert out.completion == "ANSWER:B"

    def test_answer_bolded(self):
        out = ANSWER_BOLDED.apply(case("ANSWER: B"))
        assert out is not None
        assert out.completion == "ANSWER: **B**"

    def test_answer_bolded_not_applicable_when_already_bold(self):
        assert ANSWER_BOLDED.apply(case("ANSWER: **B**")) is None

    def test_answer_bolded_not_applicable_without_a_cue(self):
        assert ANSWER_BOLDED.apply(case("just prose")) is None

    def test_rewrites_only_the_completion(self):
        before = case("ANSWER: TRUE", target="TRUE", metadata={"k": 1})
        after = CUE_CASE_FLIP.apply(before)
        assert after is not None
        assert changed_fields(before, after) == {"completion"}



class TestBadTransformations:
    """A broken transformation must be blamed on the transformation, never on the scorer."""

    def _bad(self, apply, mutates=("completion",)):
        return transform("bad", [CUE_CASE], list(mutates), apply)

    def test_undeclared_mutation_of_target(self):
        t = self._bad(lambda c: Case(completion=c.completion, target="CHANGED"))
        before = [case()]
        after = [t.apply(before[0])]
        v = verify_transformation(t, before, after)
        assert v is not None
        assert v.kind is ViolationKind.UNDECLARED_MUTATION
        assert "target" in v.detail
        assert v.is_error

    def test_undeclared_mutation_of_metadata(self):
        t = self._bad(
            lambda c: Case(completion="x", target=c.target, metadata={"injected": True})
        )
        before = [case(metadata={"k": 1})]
        after = [t.apply(before[0])]
        v = verify_transformation(t, before, after)
        assert v is not None
        assert v.kind is ViolationKind.UNDECLARED_MUTATION
        assert "metadata" in v.detail

    def test_dropping_a_case(self):
        t = self._bad(lambda c: c)
        v = verify_transformation(t, [case(), case(completion="b")], [case()])
        assert v is not None
        assert v.kind is ViolationKind.CASE_COUNT_CHANGED
        assert v.is_error

    def test_adding_a_case(self):
        t = self._bad(lambda c: c)
        v = verify_transformation(t, [case()], [case(), case(completion="b")])
        assert v is not None
        assert v.kind is ViolationKind.CASE_COUNT_CHANGED

    def test_duplicating_a_case_while_keeping_the_count(self):
        # count is preserved, but case 1 has been replaced by a copy of case 0, which silently
        # reweights every aggregate metric
        t = self._bad(lambda c: c)
        before = [case(completion="a"), case(completion="b")]
        after = [case(completion="a"), case(completion="a")]
        v = verify_transformation(t, before, after)
        assert v is not None
        assert v.kind is ViolationKind.CASE_DUPLICATED
        assert v.is_error

    def test_pre_existing_duplicates_are_not_blamed_on_the_transform(self):
        t = self._bad(lambda c: c)
        before = [case(completion="a"), case(completion="a")]
        after = [case(completion="x"), case(completion="x")]
        v = verify_transformation(t, before, after)
        assert v is None or v.kind is not ViolationKind.CASE_DUPLICATED

    def test_no_op_is_not_an_error_but_is_not_a_pass_either(self):
        t = self._bad(lambda c: c)
        before = [case()]
        v = verify_transformation(t, before, [case()])
        assert v is not None
        assert v.kind is ViolationKind.NO_OP
        assert not v.is_error  # NOT_APPLICABLE, not ERROR

    def test_a_well_behaved_transformation_verifies_clean(self):
        before = [case("ANSWER: TRUE"), case("ANSWER: FALSE")]
        after = [CUE_CASE_FLIP.apply(c) for c in before]
        assert verify_transformation(CUE_CASE_FLIP, before, after) is None

    def test_violation_names_the_transform_not_the_scorer(self):
        t = self._bad(lambda c: Case(completion=c.completion, target="CHANGED"))
        v = verify_transformation(t, [case()], [t.apply(case())])
        assert v is not None
        assert v.transform == "bad"
        assert "scorer" not in str(v).lower()

    def test_returns_none_rather_than_an_unchanged_case(self):
        # None means NOT_APPLICABLE; returning the input would be a guaranteed PASS
        assert CUE_CASE_FLIP.apply(case(completion="no caps here")) is None
