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
# Concrete rewrites, in two families.
#
# CUE-ANCHORED rewrites look for a known answer cue ("ANSWER:", "VERDICT:"). They are precise when
# the convention matches and useless when it does not.
#
# TARGET-ANCHORED rewrites locate the target's own occurrence in the completion and perturb that.
# They exist because a measured sweep of 62 real inspect_evals scorers found that of the 8 the
# package could observe at all, only 2 had any cue-anchored transformation apply. Every scorer has
# a target; not every scorer uses a cue word this library can guess.
# --------------------------------------------------------------------------------------

_CUE = re.compile(r"(?i)\b(ANSWER|VERDICT|GRADE|FINAL ANSWER)(\s*):(\s*)")


def _map_completion(case: Case, fn: Callable[[str], str | None]) -> Case | None:
    """Rewrite the completion with `fn`. None from `fn` means there was nothing to rewrite.

    Returning None propagates, so the framework reads it as NOT_APPLICABLE rather than as a pass.
    A transformation must never return the input unchanged to mean "not applicable".
    """
    new = fn(case.completion)
    if new is None or new == case.completion:
        return None
    return case.with_completion(new)


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
    apply=lambda c: _map_completion(c, _flip_answer_token_case),
)

CUE_SPACE_REMOVED = transform(
    name="cue_space_removed",
    tests=[CUE_WHITESPACE],
    mutates=["completion"],
    apply=lambda c: _map_completion(c, _strip_cue_space),
)

ANSWER_BOLDED = transform(
    name="answer_bolded",
    tests=[MARKUP],
    mutates=["completion"],
    apply=lambda c: _map_completion(c, _wrap_answer_in_bold),
)

# ---- target-anchored ----------------------------------------------------------------


def _targets_of(case: Case) -> list[str]:
    raw = case.target if isinstance(case.target, list) else [case.target]
    return [t for t in raw if t and t.strip()]


def _sub_target(case: Case, rewrite: Callable[[str], str | None]) -> Case | None:
    """Apply `rewrite` to each whole-word occurrence of the target inside the completion.

    Word-boundary anchored, which matters: a target of "A" against a completion of "ANSWER: A"
    must not rewrite the "A" inside "ANSWER". Returns None when nothing changed, so the framework
    reads it as NOT_APPLICABLE rather than as a pass.
    """
    text = case.completion
    for target in _targets_of(case):
        replacement = rewrite(target)
        if replacement is None or replacement == target:
            continue
        pattern = re.compile(rf"(?<![\w*`]){re.escape(target)}(?![\w*`])")
        text = pattern.sub(lambda _m, r=replacement: r, text)  # type: ignore[misc]
    if text == case.completion:
        return None
    return case.with_completion(text)


def _flip_case(token: str) -> str | None:
    """'TRUE' -> 'True'; 'true' -> 'TRUE'. None when the token has no case to flip."""
    if not any(c.isalpha() for c in token):
        return None
    flipped = token.title() if token.isupper() else token.upper()
    return None if flipped == token else flipped


TARGET_CASE_FLIP = transform(
    name="target_case_flip",
    tests=[CUE_CASE],
    mutates=["completion"],
    apply=lambda c: _sub_target(c, _flip_case),
)

TARGET_BOLDED = transform(
    name="target_bolded",
    tests=[MARKUP],
    mutates=["completion"],
    apply=lambda c: _sub_target(c, lambda t: f"**{t}**"),
)

TARGET_SPACE_PADDED = transform(
    name="target_space_padded",
    tests=[CUE_WHITESPACE],
    mutates=["completion"],
    apply=lambda c: _sub_target(c, lambda t: f" {t} "),
)


BUILTIN_TRANSFORMS: tuple[Transform, ...] = (
    # cue-anchored
    CUE_CASE_FLIP,
    CUE_SPACE_REMOVED,
    ANSWER_BOLDED,
    # target-anchored
    TARGET_CASE_FLIP,
    TARGET_BOLDED,
    TARGET_SPACE_PADDED,
)


def transforms_for(invariant: Invariant) -> tuple[Transform, ...]:
    return tuple(t for t in BUILTIN_TRANSFORMS if t.valid_for(invariant))
