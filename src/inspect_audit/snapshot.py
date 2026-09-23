"""Dataset snapshots: the observable state of an evaluation's sample population.

A snapshot records, for every sample the task would evaluate, a CONTENT HASH plus the fields a diff
reports on. Identity is the content hash, not the sample id: ids can change without the content
changing, and can repeat (worldsense before inspect_evals #940 had 87,048 rows under 40,176 ids), so
matching on ids is both misleading and undefined.

Content = input text + choices + target. Message ids are excluded on purpose: Inspect assigns a random
id to every ChatMessage, so hashing the message objects would make every sample look new.
"""

from __future__ import annotations

import hashlib
import inspect as pyinspect
import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

SNAPSHOT_FORMAT = 1


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = []
        for m in value:
            role = getattr(m, "role", "")
            text = getattr(m, "text", None)
            parts.append(f"{role}:{text if text is not None else m}")
        return "\n".join(parts)
    return str(value)


def _target(value: Any) -> str:
    return " | ".join(str(v) for v in value) if isinstance(value, list) else str(value)


def _choices(value: Any) -> list[str]:
    return [str(getattr(c, "value", c)) for c in (value or [])]


def _scalar_metadata(md: dict[str, Any] | None) -> dict[str, Any]:
    """Keep scalar metadata only; containers are summarised by a hash so changes stay visible."""
    out: dict[str, Any] = {}
    for k, v in (md or {}).items():
        if isinstance(v, (str, int, float, bool)) or v is None:
            out[k] = v
        else:
            blob = json.dumps(v, sort_keys=True, default=str)
            out[k] = "sha256:" + hashlib.sha256(blob.encode()).hexdigest()[:16]
    return out


def content_hash(input_text: str, choices: list[str], target: str) -> str:
    blob = json.dumps([input_text, choices, target], ensure_ascii=False)
    return hashlib.sha256(blob.encode()).hexdigest()


@dataclass(frozen=True)
class SampleRecord:
    content: str
    id: str | None
    target: str
    choices: tuple[str, ...]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Snapshot:
    task: str
    records: list[SampleRecord]
    info: dict[str, Any] = field(default_factory=dict)

    def save(self, path: str | Path) -> None:
        with open(path, "w") as f:
            header = {"format": SNAPSHOT_FORMAT, "task": self.task, "n": len(self.records),
                      "info": self.info}
            f.write(json.dumps({"header": header}) + "\n")
            for r in self.records:
                d = asdict(r)
                d["choices"] = list(r.choices)
                # ASCII-escaped on purpose: raw U+2028 etc. inside a record would be split by
                # str.splitlines(), which is how the first sciknoweval replay failed.
                f.write(json.dumps(d, default=str) + "\n")

    @classmethod
    def load(cls, path: str | Path) -> Snapshot:
        with open(path) as f:
            lines = [ln for ln in f.read().split("\n") if ln]
        if not lines:
            raise ValueError(f"{path}: empty snapshot file")
        header = json.loads(lines[0]).get("header")
        if not header or header.get("format") != SNAPSHOT_FORMAT:
            raise ValueError(f"{path}: not an inspect-audit snapshot (format {SNAPSHOT_FORMAT})")
        records = []
        for line in lines[1:]:
            d = json.loads(line)
            records.append(SampleRecord(content=d["content"], id=d["id"], target=d["target"],
                                        choices=tuple(d["choices"]), metadata=d["metadata"]))
        if len(records) != header["n"]:
            raise ValueError(f"{path}: header says {header['n']} records, file has {len(records)}")
        return cls(task=header["task"], records=records, info=header.get("info", {}))


def records_from_samples(samples: Iterable[Any]) -> list[SampleRecord]:
    records = []
    for s in samples:
        text, choices, target = _text(s.input), _choices(s.choices), _target(s.target)
        records.append(SampleRecord(content=content_hash(text, choices, target),
                                    id=None if s.id is None else str(s.id), target=target,
                                    choices=tuple(choices), metadata=_scalar_metadata(s.metadata)))
    return records


def _lookup_task(task_name: str) -> Any:
    """Resolve a registered task by name. Inspect has no public API for this, so the two private
    calls are isolated here and any change to them surfaces as an explicit error, never a silent
    wrong result."""
    try:
        from inspect_ai._util.entrypoints import ensure_entry_points
        from inspect_ai._util.registry import registry_lookup
    except ImportError as e:  # pragma: no cover - depends on the installed inspect_ai
        raise RuntimeError(
            "inspect-audit could not import Inspect's task registry "
            f"({e}); this inspect_ai version is unsupported") from e
    ensure_entry_points()
    return registry_lookup("task", task_name)


def snapshot_task(task_name: str, task_args: dict[str, Any] | None = None) -> Snapshot:
    """Build the task's dataset exactly as an eval would, and snapshot it. No model is called.

    `shuffle=False` is passed when the task accepts it, so the snapshot is deterministic; the diff
    compares multisets, so order never matters, but some tasks shuffle BEFORE deduplicating, which
    changes which rows survive. Whether that was possible is recorded, not hidden.
    """
    fn = _lookup_task(task_name)
    if fn is None:
        raise LookupError(f"task {task_name!r} not found in the Inspect registry")
    args = dict(task_args or {})
    accepts_shuffle = "shuffle" in pyinspect.signature(fn).parameters
    if accepts_shuffle and "shuffle" not in args:
        args["shuffle"] = False
    task = fn(**args)
    return Snapshot(task=task_name, records=records_from_samples(task.dataset),
                    info={"task_args": args, "shuffle_disabled": accepts_shuffle
                          and args.get("shuffle") is False})
