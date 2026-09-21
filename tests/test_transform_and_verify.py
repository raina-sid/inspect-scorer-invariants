"""Tests for the transformation contract and its runtime enforcement.

The important ones are in TestBadTransformations: the framework must blame a broken
transformation, never the scorer.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from inspect_scorer_probes.case import FIELDS, Case, changed_fields
from inspect_scorer_probes.invariants import CUE_CASE, CUE_WHITESPACE, MARKUP
from inspect_scorer_probes.transform import (
    ANSWER_BOLDED,
    BUILTIN_TRANSFORMS,
    CUE_CASE_FLIP,
    CUE_SPACE_REMOVED,
    TARGET_BOLDED,
    TARGET_CASE_FLIP,
    TARGET_SPACE_PADDED,
    Transform,
    transform,
    transforms_for,
)
from inspect_scorer_probes.verify import ViolationKind, verify_transformation


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


class TestTargetAnchoredRewrites:
    """Target-anchored transformations exist because cue-anchored ones reach too little.

    Measured: of 62 real inspect_evals scorers, 8 could be observed at all, and only 2 had any
    cue-anchored transformation apply. Every scorer has a target; not every scorer uses a cue word
    this library can guess. After adding these, all 8 were exercised.
    """

    def test_word_boundary_protects_the_cue(self):
        # THE trap: target "A" must not rewrite the A inside "ANSWER"
        out = TARGET_BOLDED.apply(case("ANSWER: A", target="A"))
        assert out is not None
        assert out.completion == "ANSWER: **A**"

    def test_bolds_a_multiword_target(self):
        out = TARGET_BOLDED.apply(case("The answer is Paris.", target="Paris"))
        assert out is not None
        assert out.completion == "The answer is **Paris**."

    def test_flips_case_both_directions(self):
        up = TARGET_CASE_FLIP.apply(case("TRUE", target="TRUE"))
        down = TARGET_CASE_FLIP.apply(case("Reasoning.\nFINAL: true", target="true"))
        assert up is not None and up.completion == "True"
        assert down is not None and down.completion == "Reasoning.\nFINAL: TRUE"

    def test_pads_whitespace_around_the_target(self):
        out = TARGET_SPACE_PADDED.apply(case("ANSWER:B", target="B"))
        assert out is not None
        assert out.completion == "ANSWER: B "

    def test_every_target_of_a_list_is_rewritten(self):
        out = TARGET_BOLDED.apply(case("A and B both", target=["A", "B"]))
        assert out is not None
        assert out.completion == "**A** and **B** both"

    def test_repeated_occurrences_all_rewritten(self):
        out = TARGET_BOLDED.apply(case("B then B again", target="B"))
        assert out is not None
        assert out.completion == "**B** then **B** again"

    @pytest.mark.parametrize(
        ("t", "completion", "target"),
        [
            (TARGET_BOLDED, "ANSWER: **A**", "A"),        # already bold
            (TARGET_BOLDED, "no target here", "Zebra"),   # target absent
            (TARGET_CASE_FLIP, "the answer is 42", "42"), # nothing to case-flip
            (TARGET_BOLDED, "x", ""),                     # empty target
        ],
    )
    def test_returns_none_rather_than_an_unchanged_case(self, t, completion, target):
        # None means NOT_APPLICABLE; returning the input would be a guaranteed PASS
        assert t.apply(case(completion, target=target)) is None

    def test_only_the_completion_is_mutated(self):
        before = case("ANSWER: A", target="A", metadata={"k": 1})
        after = TARGET_BOLDED.apply(before)
        assert after is not None
        assert changed_fields(before, after) == {"completion"}

    def test_each_declares_the_invariant_it_tests(self):
        assert TARGET_CASE_FLIP.valid_for(CUE_CASE)
        assert TARGET_BOLDED.valid_for(MARKUP)
        assert TARGET_SPACE_PADDED.valid_for(CUE_WHITESPACE)
        assert not TARGET_BOLDED.valid_for(CUE_CASE)


class TestCaseInput:
    """Case.input exists because three measured scorers were unreachable without it."""

    def test_defaults_to_empty_and_is_a_declarable_field(self):
        assert case().input == ""
        assert "input" in FIELDS

    def test_reaches_a_scorer_that_reads_state_input(self):
        from inspect_ai.scorer import CORRECT, INCORRECT, Score, accuracy, scorer

        from inspect_scorer_probes.pipeline import observe, resolve_metrics

        @scorer(metrics=[accuracy()])
        def input_reading_scorer():
            async def score(state, target):
                return Score(value=CORRECT if target.text in state.input else INCORRECT)

            return score

        cases = [Case(completion="x", target="Paris", input="Where? Paris.")]
        obs = observe(input_reading_scorer(), resolve_metrics([accuracy()]), cases)
        assert obs.metrics["accuracy"] == 1.0

    def test_an_undeclared_input_mutation_is_caught(self):
        from inspect_scorer_probes.verify import ViolationKind, verify_transformation

        bad = transform(
            "input_mutator", [CUE_CASE], ["completion"],
            lambda c: Case(completion=c.completion.title(), target=c.target, input="TAMPERED"),
        )
        before = [case("ANSWER: TRUE", target="TRUE")]
        after = [bad.apply(before[0])]
        v = verify_transformation(bad, before, after)
        assert v is not None
        assert v.kind is ViolationKind.UNDECLARED_MUTATION
        assert "input" in v.detail
