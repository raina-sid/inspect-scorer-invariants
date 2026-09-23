"""Observed differences between two dataset states. Reports what changed; never says whether it matters.

States are compared as MULTISETS of content hashes, so row order is irrelevant and duplicates are
counted, not collapsed. Categories:

  removed           content present in `before` more times than in `after`
  added             the reverse
  id_changed        same content in both, but its sample ids differ
  metadata_changed  same content in both, but its metadata differs

Group decomposition is part of the result, not decoration: a change can be small in total and
total within one group (sciknoweval at inspect_evals #940 lost ~5% overall and ~99% of one task).
"""

from __future__ import annotations

import collections
from dataclasses import dataclass, field
from typing import Any

from .snapshot import SampleRecord, Snapshot

MAX_GROUP_VALUES = 50
EXAMPLES = 5


@dataclass
class GroupDelta:
    key: str            # metadata key, or "target"
    value: str
    before: int
    after: int

    @property
    def delta(self) -> int:
        return self.after - self.before


@dataclass
class DatasetDiff:
    before_task: str
    after_task: str
    n_before: int
    n_after: int
    removed: int
    added: int
    unchanged: int
    id_changed: int
    metadata_changed: int
    examples: dict[str, list[str]] = field(default_factory=dict)
    groups: list[GroupDelta] = field(default_factory=list)
    skipped_group_keys: list[str] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not (self.removed or self.added or self.id_changed or self.metadata_changed)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "dataset_diff", "before_task": self.before_task, "after_task": self.after_task,
            "samples": {"before": self.n_before, "after": self.n_after, "removed": self.removed,
                        "added": self.added, "unchanged": self.unchanged,
                        "id_changed": self.id_changed, "metadata_changed": self.metadata_changed},
            "examples": self.examples,
            "groups": [{"key": g.key, "value": g.value, "before": g.before, "after": g.after,
                        "delta": g.delta} for g in self.groups],
            "skipped_group_keys": self.skipped_group_keys,
            "empty": self.empty,
        }


def _index(records: list[SampleRecord]) -> dict[str, list[SampleRecord]]:
    ix: dict[str, list[SampleRecord]] = collections.defaultdict(list)
    for r in records:
        ix[r.content].append(r)
    return ix


def _ids(rs: list[SampleRecord]) -> list[str]:
    return sorted(str(r.id) for r in rs)


def _meta_key(r: SampleRecord) -> str:
    return repr(sorted(r.metadata.items(), key=lambda kv: kv[0]))


def diff_datasets(before: Snapshot, after: Snapshot) -> DatasetDiff:
    a, b = _index(before.records), _index(after.records)
    removed = added = unchanged = id_changed = metadata_changed = 0
    ex: dict[str, list[str]] = collections.defaultdict(list)

    for h in set(a) | set(b):
        ra, rb = a.get(h, []), b.get(h, [])
        common = min(len(ra), len(rb))
        unchanged += common
        if len(ra) > len(rb):
            removed += len(ra) - len(rb)
            if len(ex["removed"]) < EXAMPLES:
                ex["removed"].append(str(ra[-1].id))
        elif len(rb) > len(ra):
            added += len(rb) - len(ra)
            if len(ex["added"]) < EXAMPLES:
                ex["added"].append(str(rb[-1].id))
        if common:
            # Count changes over the MATCHED copies only. Comparing whole lists was wrong: removing
            # one of two identical duplicates made the lists differ in length, so an untouched
            # sample read as "metadata changed" (408 phantom cases in the sciknoweval replay).
            same_ids = sum((collections.Counter(_ids(ra)) & collections.Counter(_ids(rb))).values())
            if common - min(common, same_ids):
                id_changed += common - min(common, same_ids)
                if len(ex["id_changed"]) < EXAMPLES:
                    ex["id_changed"].append(f"{ra[0].id} -> {rb[0].id}")
            same_md = sum((collections.Counter(map(_meta_key, ra))
                           & collections.Counter(map(_meta_key, rb))).values())
            if common - min(common, same_md):
                metadata_changed += common - min(common, same_md)
                if len(ex["metadata_changed"]) < EXAMPLES:
                    ex["metadata_changed"].append(str(rb[0].id))

    groups, skipped = _group_deltas(before.records, after.records)
    return DatasetDiff(before_task=before.task, after_task=after.task,
                       n_before=len(before.records), n_after=len(after.records), removed=removed,
                       added=added, unchanged=unchanged, id_changed=id_changed,
                       metadata_changed=metadata_changed, examples=dict(ex), groups=groups,
                       skipped_group_keys=skipped)


def _group_deltas(ra: list[SampleRecord], rb: list[SampleRecord]
                  ) -> tuple[list[GroupDelta], list[str]]:
    def counts(records: list[SampleRecord]) -> dict[str, collections.Counter[str]]:
        c: dict[str, collections.Counter[str]] = collections.defaultdict(collections.Counter)
        for r in records:
            c["target"][r.target] += 1
            for k, v in r.metadata.items():
                if isinstance(v, str) and v.startswith("sha256:"):
                    continue
                c[k][str(v)] += 1
        return c

    ca, cb = counts(ra), counts(rb)
    out: list[GroupDelta] = []
    skipped: list[str] = []
    for key in sorted(set(ca) | set(cb)):
        values = set(ca.get(key, {})) | set(cb.get(key, {}))
        if len(values) > MAX_GROUP_VALUES:
            skipped.append(key)
            continue
        for v in sorted(values):
            before, after = ca.get(key, collections.Counter())[v], cb.get(key, collections.Counter())[v]
            if before != after:
                out.append(GroupDelta(key=key, value=v, before=before, after=after))
    # largest relative loss first: that is where a reader should look
    out.sort(key=lambda g: (g.delta / g.before if g.before else float("inf"), g.key, g.value))
    return out, skipped
