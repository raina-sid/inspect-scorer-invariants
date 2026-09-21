"""Metamorphic invariance probes for Inspect AI scoring pipelines.

    given a contract C and a transformation T, does pipeline P satisfy C?

The package never decides whether C is semantically right for the task. That judgment stays with
the caller, and is recorded with a hash of it.
"""

from .case import Case
from .contract import Contract, Invariant, Outcome, Relation, Tolerance
from .invariants import (
    ALL_INVARIANTS,
    CODE_FORMATTING,
    CUE_CASE,
    CUE_WHITESPACE,
    MARKUP,
    WITHOUT_BUILTIN_TRANSFORMATION,
    WRONG_STAYS_INCORRECT,
    by_name,
)
from .probe import probe, probe_async
from .report import (
    InvariantViolation,
    ProbeReport,
    ProbeResult,
    ReproductionScaffold,
    assert_invariants,
)
from .transform import Transform, transform

__all__ = [
    "ALL_INVARIANTS",
    "CODE_FORMATTING",
    "CUE_CASE",
    "CUE_WHITESPACE",
    "MARKUP",
    "WITHOUT_BUILTIN_TRANSFORMATION",
    "WRONG_STAYS_INCORRECT",
    "Case",
    "Contract",
    "Invariant",
    "InvariantViolation",
    "Outcome",
    "ProbeReport",
    "ProbeResult",
    "Relation",
    "ReproductionScaffold",
    "Tolerance",
    "Transform",
    "assert_invariants",
    "by_name",
    "probe",
    "probe_async",
    "transform",
]
