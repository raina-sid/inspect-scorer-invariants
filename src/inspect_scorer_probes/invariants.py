"""The five invariants that ship in v1.

These are the families that survived a pre-registered run against 18 Inspect evals. Two others
were in the frozen set and are deliberately absent:

    NUMERIC_EQUIVALENT      found nothing across 18 evals
    LEGITIMATE_DISTRACTOR   found nothing across 18 evals

Shipping either would claim coverage that was measured at zero. The pre-registration and its
results are recorded in the design doc rather than reconstructed here.
"""

from __future__ import annotations

from .contract import Invariant, Relation

CUE_WHITESPACE = Invariant(
    name="CUE_WHITESPACE",
    relation=Relation.EQUAL,
    description=(
        "The observation does not depend on whitespace around the answer cue. "
        "A model writing 'ANSWER:B' rather than 'ANSWER: B' selected the same answer."
    ),
)

CUE_CASE = Invariant(
    name="CUE_CASE",
    relation=Relation.EQUAL,
    description=(
        "The observation does not depend on the case of the answer cue or the answer token. "
        "'True' and 'TRUE' are the same answer."
    ),
)

MARKUP = Invariant(
    name="MARKUP",
    relation=Relation.EQUAL,
    description=(
        "The observation does not depend on markdown emphasis around the cue or the answer. "
        "'**B**' is the same answer as 'B'. Exclude this where the task mandates an exact "
        "output layout -- many prompts say 'no other text', which voids the assertion."
    ),
)

CODE_FORMATTING = Invariant(
    name="CODE_FORMATTING",
    relation=Relation.EQUAL,
    description=(
        "The observation does not depend on semantics-preserving code formatting: "
        "reindentation, a blank line after the signature, a hoisted import, or fence-tag case. "
        "SHIPS NO TRANSFORMATION -- supply your own, or this can only return NOT_APPLICABLE. "
        "Nothing ships because every code scorer in inspect_evals executes code in a sandbox, "
        "outside V0.1 scope, so there was no real scorer to validate a shipped rewrite against."
    ),
)

WRONG_STAYS_INCORRECT = Invariant(
    name="WRONG_STAYS_INCORRECT",
    relation=Relation.STAYS_INCORRECT,
    description=(
        "Replacing a wrong answer with a differently-wrong answer of the same surface shape "
        "leaves the verdict incorrect. This is the only invariant that tests the "
        "false-positive direction, and the only one whose relation is not equality. "
        "SHIPS NO TRANSFORMATION -- supply your own, or this can only return NOT_APPLICABLE."
    ),
)

#: Declared but shipping NO built-in transformation. Probing one of these without supplying your own
#: transformation can only return NOT_APPLICABLE. Pinned by a test so a future invariant cannot
#: silently become a third advertised-but-dead entry.
WITHOUT_BUILTIN_TRANSFORMATION: frozenset[str] = frozenset(
    {"CODE_FORMATTING", "WRONG_STAYS_INCORRECT"}
)

#: Every invariant shipped in v1, in a stable order.
ALL_INVARIANTS: tuple[Invariant, ...] = (
    CUE_WHITESPACE,
    CUE_CASE,
    MARKUP,
    CODE_FORMATTING,
    WRONG_STAYS_INCORRECT,
)

_BY_NAME = {i.name: i for i in ALL_INVARIANTS}


def by_name(name: str) -> Invariant:
    """Look up a shipped invariant by name, for deserialising a recorded contract."""
    try:
        return _BY_NAME[name]
    except KeyError:
        raise KeyError(
            f"unknown invariant {name!r}; shipped: {sorted(_BY_NAME)}"
        ) from None
