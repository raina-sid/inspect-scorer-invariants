"""Runtime enforcement of a transformation's own contract.

This is what makes "a bad transformation must ERROR" a property of the framework rather than an
aspiration of its test suite. The framework does not take a transformation's word for what it did:
after applying, it diffs the cases against the declaration.

Every violation here is attributed to the TRANSFORMATION, never to the scorer. A scorer must never
be reported as failing because the thing probing it was wrong.

WHAT THIS VERIFIES, PRECISELY. Structural compliance only: which Case fields changed, and that the
case count is preserved. It cannot and does not establish SEMANTIC preservation -- that flipping
case, or wrapping an answer in asterisks, leaves the meaning intact. That claim lives in the
caller-declared invariant, which is why the contract is recorded and hashed rather than inferred.
A transformation can be perfectly compliant here and still be semantically wrong, in which case the
resulting FAIL is the caller's error, not the scorer's.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .case import Case, changed_fields
from .transform import Transform


class ViolationKind(Enum):
    #: changed a Case field it did not declare in `mutates`
    UNDECLARED_MUTATION = "undeclared_mutation"
    #: added or dropped cases
    CASE_COUNT_CHANGED = "case_count_changed"
    #: produced a duplicate the input did not contain
    CASE_DUPLICATED = "case_duplicated"
    #: changed nothing at all, so any comparison would pass vacuously
    NO_OP = "no_op"


@dataclass(frozen=True)
class Violation:
    kind: ViolationKind
    transform: str
    detail: str

    #: NO_OP is not an error -- there was simply nothing to test here. Everything else is a
    #: broken transformation and must surface as ERROR, never as a scorer FAIL.
    @property
    def is_error(self) -> bool:
        return self.kind is not ViolationKind.NO_OP

    def __str__(self) -> str:
        return f"{self.transform}: {self.kind.value}: {self.detail}"


def verify_transformation(
    transform: Transform, before: list[Case], after: list[Case]
) -> Violation | None:
    """Check the applied transformation against what it declared. None means it behaved."""
    if "case_count" in transform.holds_fixed and len(before) != len(after):
        return Violation(
            kind=ViolationKind.CASE_COUNT_CHANGED,
            transform=transform.name,
            detail=f"{len(before)} cases in, {len(after)} out",
        )

    if len(before) != len(after):
        # cannot pair them up, so nothing further is checkable
        return None

    new_duplicates = _new_duplicates(before, after)
    if new_duplicates:
        return Violation(
            kind=ViolationKind.CASE_DUPLICATED,
            transform=transform.name,
            detail=f"produced {new_duplicates} duplicate case(s) absent from the input",
        )

    any_change = False
    for index, (b, a) in enumerate(zip(before, after)):
        changed = changed_fields(b, a)
        if changed:
            any_change = True
        undeclared = changed - transform.mutates
        if undeclared:
            return Violation(
                kind=ViolationKind.UNDECLARED_MUTATION,
                transform=transform.name,
                detail=(
                    f"case {index} changed {sorted(undeclared)}, which is not in "
                    f"mutates={sorted(transform.mutates)}"
                ),
            )

    if not any_change:
        return Violation(
            kind=ViolationKind.NO_OP,
            transform=transform.name,
            detail="no case changed, so any comparison would pass vacuously",
        )

    return None


def _new_duplicates(before: list[Case], after: list[Case]) -> int:
    """How many duplicate cases exist in `after` that were not already duplicated in `before`.

    A transformation can keep the case count identical while replacing one case with a copy of
    another, which silently reweights every aggregate metric.
    """
    return max(0, _duplicate_count(after) - _duplicate_count(before))


def _duplicate_count(cases: list[Case]) -> int:
    seen: list[Case] = []
    duplicates = 0
    for case in cases:
        if any(case == s for s in seen):
            duplicates += 1
        else:
            seen.append(case)
    return duplicates
