"""Metamorphic invariance probes for Inspect AI scoring pipelines."""

from .contract import Contract, Invariant, Outcome, Relation, Tolerance, contract
from .invariants import (
    ALL_INVARIANTS,
    CODE_FORMATTING,
    CUE_CASE,
    CUE_WHITESPACE,
    MARKUP,
    WRONG_STAYS_INCORRECT,
    by_name,
)

__all__ = [
    "ALL_INVARIANTS",
    "CODE_FORMATTING",
    "CUE_CASE",
    "CUE_WHITESPACE",
    "MARKUP",
    "WRONG_STAYS_INCORRECT",
    "Contract",
    "Invariant",
    "Outcome",
    "Relation",
    "Tolerance",
    "by_name",
    "contract",
]
