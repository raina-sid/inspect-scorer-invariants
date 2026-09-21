"""Transformations, and the contract each one declares about itself.

Note the direction of the declaration. A case-flip does not *preserve* case -- it *changes* case
while holding meaning fixed. So a transformation declares:

    tests        which invariant it is valid evidence for
    mutates      which Case fields it is licensed to change
    holds_fixed  which Case fields, and which structural properties, it must not change

If a transformation does not claim to test the invariant under examination, the result is
NOT_APPLICABLE -- never FAIL. That is what stops this library smuggling its own assumptions into
someone else's test.

Declaring both `mutates` and `holds_fixed` is deliberate double-entry bookkeeping: the two must be
disjoint and must jointly account for every field, so a self-contradictory or incomplete
declaration is rejected when the Transform is constructed rather than producing a confusing result
at probe time.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from .case import FIELDS, Case
from .contract import Invariant
from .invariants import CUE_CASE, CUE_WHITESPACE, MARKUP

#: Structural properties a transformation can be required to preserve. These are not Case fields.
STRUCTURAL: frozenset[str] = frozenset({"case_count"})


@dataclass(frozen=True)
class Transform:
    """One concrete rewrite, plus the contract it declares about itself.

    `apply` returns a new Case, or None to say "this rewrite cannot be expressed for this case".
    Returning None is how a transformation reports NOT_APPLICABLE for a specific case; it must
    never return the input unchanged to mean the same thing, because an unchanged input would
    produce a vacuous PASS.
    """

    name: str
    tests: frozenset[Invariant]
    mutates: frozenset[str]
    holds_fixed: frozenset[str]
    apply: Callable[[Case], Case | None] = field(compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "tests", frozenset(self.tests))
        object.__setattr__(self, "mutates", frozenset(self.mutates))
        object.__setattr__(self, "holds_fixed", frozenset(self.holds_fixed))

        if not self.tests:
            raise ValueError(f"{self.name}: tests must name at least one invariant")
        if not self.mutates:
            raise ValueError(
                f"{self.name}: mutates must be non-empty -- a transformation that changes "
                "nothing produces a vacuous PASS"
            )

        unknown_m = self.mutates - FIELDS
        if unknown_m:
            raise ValueError(f"{self.name}: mutates names non-Case fields {sorted(unknown_m)}")

        unknown_h = self.holds_fixed - (FIELDS | STRUCTURAL)
        if unknown_h:
            raise ValueError(f"{self.name}: holds_fixed names unknown {sorted(unknown_h)}")

        overlap = self.mutates & self.holds_fixed
        if overlap:
            raise ValueError(
                f"{self.name}: contradictory declaration -- {sorted(overlap)} is both "
                "mutated and held fixed"
            )

        unaccounted = FIELDS - self.mutates - self.holds_fixed
        if unaccounted:
            raise ValueError(
                f"{self.name}: incomplete declaration -- {sorted(unaccounted)} is neither "
                "mutated nor held fixed"
            )

        if "case_count" not in self.holds_fixed:
            raise ValueError(
                f"{self.name}: must hold case_count fixed. A transformation that adds or drops "
                "cases changes every aggregate metric for trivial reasons."
            )

    def valid_for(self, invariant: Invariant) -> bool:
        return any(t.name == invariant.name for t in self.tests)


def transform(
    name: str,
    tests: Iterable[Invariant],
    mutates: Iterable[str],
    apply: Callable[[Case], Case | None],
) -> Transform:
    """Build a Transform, deriving `holds_fixed` as everything `mutates` does not name.

    The explicit two-field form stays available for a transformation that wants to state both;
    this helper covers the common case where holding everything else fixed is the intent.
    """
    mutates = frozenset(mutates)
    return Transform(
        name=name,
        tests=frozenset(tests),
        mutates=mutates,
        holds_fixed=(FIELDS - mutates) | STRUCTURAL,
        apply=apply,
    )


# --------------------------------------------------------------------------------------
# Concrete rewrites.
#
# Only the completion-side rewrites needed to exercise the machinery land here. The full set
# arrives with the pipeline, so that each one is added against a real comparison rather than
# guessed at in advance.
# --------------------------------------------------------------------------------------

_CUE = re.compile(r"(?i)\b(ANSWER|VERDICT|GRADE|FINAL ANSWER)(\s*):(\s*)")


def _map_generations(case: Case, fn: Callable[[str], str | None]) -> Case | None:
    """Apply `fn` to each generation; None from `fn` means that generation is untouched.

    Returns None if no generation changed, which the framework reads as NOT_APPLICABLE rather
    than as a pass.
    """
    gens = case.generations
    out = [fn(g) or g for g in gens]
    if out == gens:
        return None
    return case.with_completion(out if isinstance(case.completion, list) else out[0])


def _flip_answer_token_case(text: str) -> str | None:
    """Title-case an all-caps answer token: 'TRUE' -> 'True'. None if there is nothing to flip."""
    def sub(m: re.Match[str]) -> str:
        token = m.group(0)
        return token.title() if token.isupper() else token

    new = re.sub(r"\b[A-Z]{2,}\b", sub, text)
    return None if new == text else new


def _strip_cue_space(text: str) -> str | None:
    """'ANSWER: B' -> 'ANSWER:B'."""
    new = _CUE.sub(lambda m: f"{m.group(1)}{m.group(2)}:", text)
    return None if new == text else new


def _wrap_answer_in_bold(text: str) -> str | None:
    """'ANSWER: B' -> 'ANSWER: **B**'. Only the value after the cue is wrapped."""
    m = _CUE.search(text)
    if not m:
        return None
    head, tail = text[: m.end()], text[m.end() :]
    value = tail.strip()
    if not value or value.startswith("*"):
        return None
    return f"{head}**{value}**"


CUE_CASE_FLIP = transform(
    name="cue_case_flip",
    tests=[CUE_CASE],
    mutates=["completion"],
    apply=lambda c: _map_generations(c, _flip_answer_token_case),
)

CUE_SPACE_REMOVED = transform(
    name="cue_space_removed",
    tests=[CUE_WHITESPACE],
    mutates=["completion"],
    apply=lambda c: _map_generations(c, _strip_cue_space),
)

ANSWER_BOLDED = transform(
    name="answer_bolded",
    tests=[MARKUP],
    mutates=["completion"],
    apply=lambda c: _map_generations(c, _wrap_answer_in_bold),
)

BUILTIN_TRANSFORMS: tuple[Transform, ...] = (
    CUE_CASE_FLIP,
    CUE_SPACE_REMOVED,
    ANSWER_BOLDED,
)


def transforms_for(invariant: Invariant) -> tuple[Transform, ...]:
    return tuple(t for t in BUILTIN_TRANSFORMS if t.valid_for(invariant))
