"""A single scoring observation's inputs.

`Case` is what a transformation rewrites. It carries exactly what the three demonstrated defect
shapes need and nothing more:

    worldsense     several cases, so the metric layer has something to aggregate
    tau2           a scorer reading state.metadata                -> metadata
    simpleqa       a scorer reading state.input                   -> input
    novelty_bench  k generations, which that eval keeps in
                   state.metadata["all_completions"]              -> metadata

Note what is deliberately absent. An earlier draft gave `completion` the type `str | list[str]`
so that a multi-generation scorer could be probed per element. That was based on a guess about
novelty_bench which turned out to be wrong: it reads its k generations from
`state.metadata["all_completions"]`, not from the completion. Inspect does support multiple
choices on a ModelOutput, so the capability is real -- but no fixture we ship would exercise it,
and an untested path in a detector is exactly what this package exists to catch. It can be added
when a fixture needs it.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

#: The Case fields a transformation may declare that it changes. `case_count` is not a field --
#: it is a property of the case *list*, and lives in Transform.holds_fixed.
FIELDS: frozenset[str] = frozenset({"completion", "target", "metadata", "messages", "input"})


@dataclass(frozen=True)
class Case:
    """Frozen so that a transformation must return a new Case rather than edit one in place.

    Note that `metadata` is a dict and therefore still mutable in place. The framework does not
    rely on immutability to detect that -- it deep-compares against the pre-transformation value
    (see `verify`), so an in-place edit is caught rather than trusted.
    """

    completion: str
    target: str | list[str]
    metadata: dict[str, Any] | None = None
    messages: list[Any] | None = None
    #: The sample's input. Added because a measured sweep of 62 real inspect_evals scorers found
    #: three (`simpleqa`, `cti_realm` x2) that were unreachable for the sole reason that they read
    #: `state.input`. It is the same class of thing as the fields above -- a plain value the caller
    #: supplies -- unlike the store, a sandbox or `output.choices`, which a Case cannot represent.
    input: str = ""

    def field(self, name: str) -> Any:
        if name not in FIELDS:
            raise KeyError(f"unknown Case field {name!r}; known: {sorted(FIELDS)}")
        return getattr(self, name)

    def with_completion(self, completion: str) -> Case:
        return replace(self, completion=completion)

    def with_metadata(self, metadata: dict[str, Any]) -> Case:
        return replace(self, metadata=metadata)


def changed_fields(before: Case, after: Case) -> set[str]:
    """Which Case fields differ. Deep equality, so an in-place metadata edit is visible."""
    return {name for name in FIELDS if before.field(name) != after.field(name)}
