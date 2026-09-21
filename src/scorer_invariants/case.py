"""A single scoring observation's inputs.

`Case` is what a transformation rewrites. It carries exactly what the three demonstrated defect
shapes need and nothing more:

    worldsense     several cases, so the metric layer has something to aggregate
    novelty_bench  one sample whose completion is k generations -> completion: list[str]
    tau2           a scorer reading state.metadata          -> metadata
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

#: The Case fields a transformation may declare that it changes. `case_count` is not a field --
#: it is a property of the case *list*, and lives in Transform.holds_fixed.
FIELDS: frozenset[str] = frozenset({"completion", "target", "metadata", "messages"})


@dataclass(frozen=True)
class Case:
    """Frozen so that a transformation must return a new Case rather than edit one in place.

    Note that `metadata` is a dict and therefore still mutable in place. The framework does not
    rely on immutability to detect that -- it deep-compares against the pre-transformation value
    (see `verify`), so an in-place edit is caught rather than trusted.
    """

    completion: str | list[str]
    target: str | list[str]
    metadata: dict[str, Any] | None = None
    messages: list[Any] | None = None

    def field(self, name: str) -> Any:
        if name not in FIELDS:
            raise KeyError(f"unknown Case field {name!r}; known: {sorted(FIELDS)}")
        return getattr(self, name)

    def with_completion(self, completion: str | list[str]) -> Case:
        return replace(self, completion=completion)

    @property
    def generations(self) -> list[str]:
        """The completion as a list, whether it holds one string or k generations."""
        return list(self.completion) if isinstance(self.completion, list) else [self.completion]


def changed_fields(before: Case, after: Case) -> set[str]:
    """Which Case fields differ. Deep equality, so an in-place metadata edit is visible."""
    return {name for name in FIELDS if before.field(name) != after.field(name)}


def changed_generations(before: Case, after: Case) -> list[int]:
    """Which indices of a list completion differ, for reporting.

    Returns [] when the completion is a plain string, or when lengths differ (in which case the
    whole completion counts as changed and the index detail would be misleading).
    """
    if not (isinstance(before.completion, list) and isinstance(after.completion, list)):
        return []
    if len(before.completion) != len(after.completion):
        return []
    return [i for i, (b, a) in enumerate(zip(before.completion, after.completion)) if b != a]
