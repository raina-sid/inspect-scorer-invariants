"""The contract: what the caller asserts about a scoring pipeline.

The package answers one question, and the contract is the half of it the caller owns:

    Given a contract C and a transformation T, does pipeline P satisfy C?

It deliberately does NOT decide whether C is semantically right for the task. A contract is
recorded and hashed, never inferred from a prompt or a README -- inferring intent needs a model,
which would put an oracle back in the loop and make every verdict rest on that model's reading.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Relation(Enum):
    """What must hold between the baseline observation and the transformed one."""

    #: the observation must be unchanged
    EQUAL = "equal"
    #: the verdict must remain in the negative class, whatever the baseline was
    STAYS_INCORRECT = "stays_incorrect"


class Outcome(Enum):
    """The five epistemic states. ERROR and NOT_APPLICABLE must never become PASS."""

    #: contract applicable, relation holds
    PASS = "pass"
    #: contract applicable, relation violated
    FAIL = "fail"
    #: the transformation cannot meaningfully apply here
    NOT_APPLICABLE = "not_applicable"
    #: an observation or computation failed
    ERROR = "error"
    #: the caller declared the task contract rules this invariant out
    EXCLUDED = "excluded"


@dataclass(frozen=True)
class Invariant:
    """A property of a scoring pipeline, plus the relation its observations must satisfy."""

    name: str
    relation: Relation
    description: str

    def __str__(self) -> str:
        return self.name


@dataclass(frozen=True)
class Tolerance:
    """Permitted slack when comparing one metric.

    Opt-in and per-metric by design. This is exactly the knob someone would widen until a real
    change disappeared, so it is never global and it is folded into the contract hash -- loosening
    it has to be visible in the record.
    """

    absolute: float = 0.0
    relative: float = 0.0

    def __post_init__(self) -> None:
        if self.absolute < 0 or self.relative < 0:
            raise ValueError("tolerances must be non-negative")

    def permits(self, before: float, after: float) -> bool:
        delta = abs(after - before)
        return delta <= self.absolute or (
            self.relative > 0 and delta <= self.relative * abs(before)
        )


@dataclass(frozen=True)
class Contract:
    """What the caller asserts, and what the caller says does not apply.

    `invariants` is required and must be non-empty. A probe with no declared contract would have
    to either assume every invariant holds -- which manufactures false positives on any task whose
    prompt rules one out -- or assert nothing at all.
    """

    invariants: tuple[Invariant, ...]
    exclusions: tuple[Invariant, ...] = ()
    tolerances: Mapping[str, Tolerance] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # normalise sequences to tuples so callers can pass lists
        object.__setattr__(self, "invariants", tuple(self.invariants))
        object.__setattr__(self, "exclusions", tuple(self.exclusions))
        object.__setattr__(self, "tolerances", dict(self.tolerances))

        if not self.invariants:
            raise ValueError(
                "Contract.invariants must be non-empty: a probe with no declared "
                "invariant can only assume everything holds or assert nothing"
            )

        both = {i.name for i in self.invariants} & {e.name for e in self.exclusions}
        if both:
            raise ValueError(
                f"invariant(s) both asserted and excluded: {sorted(both)}"
            )

        for group, label in ((self.invariants, "invariants"), (self.exclusions, "exclusions")):
            names = [i.name for i in group]
            if len(names) != len(set(names)):
                dupes = sorted({n for n in names if names.count(n) > 1})
                raise ValueError(f"duplicate entries in {label}: {dupes}")

    def asserts(self, invariant: Invariant) -> bool:
        return any(i.name == invariant.name for i in self.invariants)

    def excludes(self, invariant: Invariant) -> bool:
        return any(e.name == invariant.name for e in self.exclusions)

    def tolerance_for(self, metric_name: str) -> Tolerance | None:
        return self.tolerances.get(metric_name)

    def to_dict(self) -> dict[str, Any]:
        """Canonical, order-independent serialisation. Two contracts that assert the same
        things serialise identically regardless of the order they were written in."""
        return {
            "invariants": sorted(
                ({"name": i.name, "relation": i.relation.value} for i in self.invariants),
                key=lambda d: d["name"],
            ),
            "exclusions": sorted(
                ({"name": e.name, "relation": e.relation.value} for e in self.exclusions),
                key=lambda d: d["name"],
            ),
            "tolerances": {
                name: {"absolute": t.absolute, "relative": t.relative}
                for name, t in sorted(self.tolerances.items())
            },
        }

    def hash(self) -> str:
        """SHA-256 over the canonical serialisation.

        Nothing prevents someone seeing a FAIL and moving that invariant into `exclusions` to
        silence it. This hash does not stop that -- it makes it visible, so a scorecard or CI job
        can pin the contract it expects.
        """
        payload = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def contract(
    invariants: Iterable[Invariant],
    exclusions: Iterable[Invariant] = (),
    tolerances: Mapping[str, Tolerance] | None = None,
) -> Contract:
    """Convenience constructor."""
    return Contract(
        invariants=tuple(invariants),
        exclusions=tuple(exclusions),
        tolerances=dict(tolerances or {}),
    )
