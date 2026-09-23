"""Human-readable rendering. Every line reports an observation; none says whether it matters."""

from __future__ import annotations

from .dataset_diff import DatasetDiff
from .score_diff import ScoreDiff

GROUP_LINES = 25


def _pct(before: int, after: int) -> str:
    if before == 0:
        return "new"
    return f"{(after - before) / before:+.1%}"


def render_dataset(d: DatasetDiff) -> str:
    out = ["DATASET DIFF", "─" * 60, f"task    {d.before_task}  ->  {d.after_task}", "",
           "samples (matched by content: input + choices + target)",
           f"  before            {d.n_before:>9,}", f"  after             {d.n_after:>9,}",
           f"  removed           {d.removed:>9,}", f"  added             {d.added:>9,}",
           f"  unchanged         {d.unchanged:>9,}",
           f"  id changed        {d.id_changed:>9,}   (same content, different sample id)",
           f"  metadata changed  {d.metadata_changed:>9,}   (same content, different metadata)"]
    for k, ids in d.examples.items():
        out.append(f"  e.g. {k}: {', '.join(ids)}")
    out += ["", "by group (largest relative loss first)"]
    if not d.groups:
        out.append("  no group changed")
    for g in d.groups[:GROUP_LINES]:
        out.append(f"  {g.key[:24]:24} {g.value[:30]:30} {g.before:>8,} -> {g.after:>8,}  "
                   f"({_pct(g.before, g.after)})")
    if len(d.groups) > GROUP_LINES:
        out.append(f"  ... {len(d.groups) - GROUP_LINES} more changed groups in --json output")
    if d.skipped_group_keys:
        out.append(f"  not decomposed (> 50 distinct values): {', '.join(d.skipped_group_keys)}")
    out += ["", "no differences observed" if d.empty else
            "observed differences above; whether they preserve comparability is your call"]
    return "\n".join(out)


def render_scores(d: ScoreDiff) -> str:
    out = ["SCORE DIFF", "─" * 60, f"before  {d.before}", f"after   {d.after}", ""]
    if d.refused:
        return "\n".join(out + [f"REFUSED: {d.refused}"])
    out.append(f"samples matched {d.matched:,}   only before {d.only_before:,}   "
               f"only after {d.only_after:,}")
    for label, names in (("scorers only before", d.scorers_only_before),
                         ("scorers only after", d.scorers_only_after)):
        if names:
            out.append(f"{label}: {', '.join(names)}")
    for s in d.scorers:
        out += ["", f"scorer {s.scorer}   [{s.case}]", f"  verdicts compared {s.compared:,}"]
        for label, n in sorted(s.transitions.items(), key=lambda kv: -kv[1]):
            out.append(f"  {label:24} {n:>6,}   e.g. {', '.join(s.examples.get(label, []))}")
        for m in s.metrics:
            mark = "changed" if m["changed"] else "same"
            out.append(f"  metric {m['name']:18} {m['before']!s:>12} -> {m['after']!s:<12} {mark}")
    out += ["", "no differences observed" if d.empty else
            "observed differences above; whether they preserve comparability is your call"]
    return "\n".join(out)
