"""Controls N2-N5 from validation/diff/PREREG.md, plus snapshot regressions."""

from __future__ import annotations

import dataclasses
import random

import pytest
from inspect_ai.dataset import Sample
from inspect_ai.model import ChatMessageSystem, ChatMessageUser

from inspect_audit import Snapshot, diff_datasets, records_from_samples


def snap(samples: list[Sample], task: str = "t") -> Snapshot:
    return Snapshot(task=task, records=records_from_samples(samples))


def base() -> list[Sample]:
    return [Sample(id=f"s{i}", input=f"question {i}", target="AB"[i % 2],
                   metadata={"group": "g1" if i < 6 else "g2"}) for i in range(10)]


def test_n2_snapshot_vs_itself_is_empty() -> None:
    s = snap(base())
    assert diff_datasets(s, s).empty


def test_n3_row_order_is_irrelevant() -> None:
    rows = base()
    shuffled = rows[:]
    random.Random(0).shuffle(shuffled)
    d = diff_datasets(snap(rows), snap(shuffled))
    assert d.empty and d.removed == d.added == 0


def test_n4_metadata_only_change_is_not_add_or_remove() -> None:
    after = base()
    after[0] = Sample(id="s0", input="question 0", target="A", metadata={"group": "renamed"})
    d = diff_datasets(snap(base()), snap(after))
    assert (d.removed, d.added, d.id_changed, d.metadata_changed) == (0, 0, 0, 1)


def test_n5_id_only_change_is_not_add_or_remove() -> None:
    after = [Sample(id=f"new-{s.id}", input=s.input, target=s.target, metadata=s.metadata)
             for s in base()]
    d = diff_datasets(snap(base()), snap(after))
    assert (d.removed, d.added, d.id_changed, d.metadata_changed) == (0, 0, 10, 0)


def test_duplicates_are_counted_as_a_multiset_not_collapsed() -> None:
    dup = base() + [Sample(id="s0", input="question 0", target="A", metadata={"group": "g1"})] * 3
    d = diff_datasets(snap(dup), snap(base()))
    assert (d.removed, d.added, d.unchanged) == (3, 0, 10)


def test_removing_one_of_two_identical_duplicates_changes_nothing_else() -> None:
    # Regression: this read as 1 metadata change and 1 id change before the multiset fix.
    one = Sample(id="d", input="q", target="A", metadata={"k": "v"})
    d = diff_datasets(snap([one, one]), snap([one]))
    assert (d.removed, d.added, d.id_changed, d.metadata_changed) == (1, 0, 0, 0)


def test_a_loss_hidden_in_the_totals_is_visible_in_the_groups() -> None:
    # 1,000 rows in a big group, 20 in a small one; lose 19 of the small group -- ~2% overall.
    before = [Sample(id=f"b{i}", input=f"big {i}", target="A", metadata={"task": "big"})
              for i in range(1000)]
    before += [Sample(id=f"s{i}", input=f"small {i}", target="A", metadata={"task": "small"})
               for i in range(20)]
    after = before[:1001]
    d = diff_datasets(snap(before), snap(after))
    assert d.removed == 19
    top = d.groups[0]
    assert (top.key, top.value, top.before, top.after) == ("task", "small", 20, 1)


def test_removed_targets_are_reported_per_label() -> None:
    after = [s for s in base() if s.target == "A"]
    d = diff_datasets(snap(base()), snap(after))
    b = next(g for g in d.groups if g.key == "target" and g.value == "B")
    assert (b.before, b.after) == (5, 0)


def test_chat_message_ids_do_not_change_identity() -> None:
    # Inspect assigns a random id to every ChatMessage; hashing message objects would make two
    # constructions of the same sample look different (the trap hit in the census).
    def build() -> Sample:
        return Sample(id="x", input=[ChatMessageSystem(content="sys"), ChatMessageUser(content="q")],
                      target="A")
    assert build().input[0].id != build().input[0].id
    assert diff_datasets(snap([build()]), snap([build()])).empty


def test_choices_are_part_of_identity() -> None:
    # sciknoweval's defect: same question text, different choices, are DIFFERENT items.
    a = Sample(id="x", input="Which compound?", choices=["aspirin", "caffeine"], target="A")
    b = Sample(id="x", input="Which compound?", choices=["methane", "benzene"], target="A")
    d = diff_datasets(snap([a]), snap([b]))
    assert (d.removed, d.added) == (1, 1)


def test_roundtrip_survives_unicode_line_separators(tmp_path) -> None:  # type: ignore[no-untyped-def]
    # Regression: the first sciknoweval replay failed because raw U+2028 inside a record was split
    # by str.splitlines() on load.
    s = snap([Sample(id="u", input="line one line two\x1cend", target="A")])
    p = tmp_path / "s.jsonl"
    s.save(p)
    loaded = Snapshot.load(p)
    assert loaded.records == s.records


def test_truncated_snapshot_is_rejected(tmp_path) -> None:  # type: ignore[no-untyped-def]
    p = tmp_path / "s.jsonl"
    snap(base()).save(p)
    lines = p.read_text().split("\n")
    p.write_text("\n".join(lines[:-3]) + "\n")
    with pytest.raises(ValueError, match="header says"):
        Snapshot.load(p)


def test_to_dict_is_json_serialisable() -> None:
    import json
    d = diff_datasets(snap(base()), snap(base()[:5]))
    assert json.loads(json.dumps(d.to_dict()))["samples"]["removed"] == 5
    assert dataclasses.is_dataclass(d)
