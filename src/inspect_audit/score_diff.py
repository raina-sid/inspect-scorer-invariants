"""Observed scoring differences between two logs of the SAME transcripts.

Intended use: take a log, re-score it with changed scorer or metric code (`inspect score`), and diff
the two. Because the transcripts are identical, any difference is attributable to the scoring code --
but ONLY if scoring is deterministic. So this refuses attribution when either log's scoring phase
called a model (observable: a ModelEvent inside Inspect's "scorers" span), and when the two logs are
not the same transcripts. It never guesses.

Per scorer it reports verdict transitions (with sample ids), metric deltas, and which of four cases
was observed:

    verdicts unchanged, metrics unchanged
    verdicts changed,   metrics changed
    verdicts changed,   metrics unchanged
    verdicts unchanged, metrics changed      <- aggregation changed while every verdict held
"""

from __future__ import annotations

import collections
import math
from dataclasses import dataclass, field
from typing import Any

from inspect_ai.event import ModelEvent, SpanBeginEvent
from inspect_ai.log import EvalLog, read_eval_log

from inspect_scorer_probes.compare import values_equal

from .snapshot import _text

SCORERS_SPAN = "scorers"  # span name Inspect opens around scoring (_eval/task/run.py, _eval/score.py)
EXAMPLES = 8


@dataclass
class ScorerDiff:
    scorer: str
    compared: int
    transitions: dict[str, int] = field(default_factory=dict)       # "C -> I": n
    examples: dict[str, list[str]] = field(default_factory=dict)    # "C -> I": [sample ids]
    metrics: list[dict[str, Any]] = field(default_factory=list)     # name, before, after, changed

    @property
    def verdicts_changed(self) -> bool:
        return bool(self.transitions)

    @property
    def metrics_changed(self) -> bool:
        return any(m["changed"] for m in self.metrics)

    @property
    def case(self) -> str:
        v = "verdicts changed" if self.verdicts_changed else "verdicts unchanged"
        m = "metrics changed" if self.metrics_changed else "metrics unchanged"
        return f"{v}, {m}"


@dataclass
class ScoreDiff:
    before: str
    after: str
    refused: str | None = None
    matched: int = 0
    only_before: int = 0
    only_after: int = 0
    scorers: list[ScorerDiff] = field(default_factory=list)
    scorers_only_before: list[str] = field(default_factory=list)
    scorers_only_after: list[str] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return (self.refused is None and not self.only_before and not self.only_after
                and not self.scorers_only_before and not self.scorers_only_after
                and not any(s.verdicts_changed or s.metrics_changed for s in self.scorers))

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "score_diff", "before": self.before, "after": self.after,
            "refused": self.refused, "empty": self.empty,
            "samples": {"matched": self.matched, "only_before": self.only_before,
                        "only_after": self.only_after},
            "scorers_only_before": self.scorers_only_before,
            "scorers_only_after": self.scorers_only_after,
            "scorers": [{"scorer": s.scorer, "compared": s.compared, "case": s.case,
                         "transitions": s.transitions, "examples": s.examples,
                         "metrics": s.metrics} for s in self.scorers],
        }


def _in_scoring(span_id: str | None, parents: dict[str, str | None], names: dict[str, str]) -> bool:
    seen = 0
    while span_id is not None and seen < 1000:  # bounded: a malformed parent chain cannot loop
        if names.get(span_id) == SCORERS_SPAN:
            return True
        span_id, seen = parents.get(span_id), seen + 1
    return False


def scoring_model_calls(log: EvalLog) -> int:
    """Count model calls made inside the scoring phase of any sample. Observed, not inferred."""
    n = 0
    for s in log.samples or []:
        parents: dict[str, str | None] = {}
        names: dict[str, str] = {}
        for e in s.events:
            if isinstance(e, SpanBeginEvent):
                parents[e.id] = e.parent_id
                names[e.id] = e.name
        n += sum(1 for e in s.events
                 if isinstance(e, ModelEvent) and _in_scoring(e.span_id, parents, names))
    return n


def _transcript_key(s: Any) -> tuple[str, str, str]:
    msgs = "\n".join(f"{m.role}:{m.text}" for m in s.messages)
    target = " | ".join(s.target) if isinstance(s.target, list) else str(s.target)
    return (_text(s.input), target, msgs)


def _metrics(log: EvalLog) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = collections.defaultdict(dict)
    for sc in (log.results.scores if log.results else []):
        for name, m in sc.metrics.items():
            out[sc.name][name] = m.value
    return out


def _same(a: Any, b: Any) -> bool:
    if isinstance(a, float) and isinstance(b, float) and not (math.isnan(a) or math.isnan(b)):
        return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-12)
    return values_equal(a, b)


def diff_logs(before: EvalLog | str, after: EvalLog | str) -> ScoreDiff:
    lb = read_eval_log(before) if isinstance(before, str) else before
    la = read_eval_log(after) if isinstance(after, str) else after
    d = ScoreDiff(before=lb.location or "<before>", after=la.location or "<after>")
    if not lb.samples or not la.samples:
        d.refused = "a log has no samples (header-only logs cannot be diffed at sample level)"
        return d

    calls = {"before": scoring_model_calls(lb), "after": scoring_model_calls(la)}
    if any(calls.values()):
        d.refused = (f"scoring called a model ({calls['before']} calls in before, "
                     f"{calls['after']} in after); differences cannot be attributed to scorer "
                     "code because a model re-roll alone can change scores")
        return d

    sb = {(s.id, s.epoch): s for s in lb.samples}
    sa = {(s.id, s.epoch): s for s in la.samples}
    keys = sorted(set(sb) & set(sa), key=str)
    d.matched, d.only_before, d.only_after = len(keys), len(set(sb) - set(sa)), len(set(sa) - set(sb))
    mismatched = [k for k in keys if _transcript_key(sb[k]) != _transcript_key(sa[k])]
    if mismatched:
        d.refused = (f"{len(mismatched)} of {len(keys)} matched samples have different transcripts "
                     f"(e.g. id={mismatched[0][0]} epoch={mismatched[0][1]}); these are not re-scorings "
                     "of the same run, so score differences cannot be attributed to scoring code")
        return d

    names_b = set().union(*((s.scores or {}).keys() for s in lb.samples))
    names_a = set().union(*((s.scores or {}).keys() for s in la.samples))
    d.scorers_only_before = sorted(names_b - names_a)
    d.scorers_only_after = sorted(names_a - names_b)
    mb, ma = _metrics(lb), _metrics(la)

    for name in sorted(names_b & names_a):
        sd = ScorerDiff(scorer=name, compared=0)
        trans: collections.Counter[str] = collections.Counter()
        ex: dict[str, list[str]] = collections.defaultdict(list)
        for k in keys:
            vb = (sb[k].scores or {}).get(name)
            va = (sa[k].scores or {}).get(name)
            xb = "<unscored>" if vb is None else vb.value
            xa = "<unscored>" if va is None else va.value
            sd.compared += 1
            if not values_equal(xb, xa):
                label = f"{xb!r} -> {xa!r}"
                trans[label] += 1
                if len(ex[label]) < EXAMPLES:
                    ex[label].append(f"{k[0]}" + (f"@{k[1]}" if k[1] != 1 else ""))
        sd.transitions, sd.examples = dict(trans), dict(ex)
        for metric in sorted(set(mb.get(name, {})) | set(ma.get(name, {}))):
            b, a = mb.get(name, {}).get(metric), ma.get(name, {}).get(metric)
            sd.metrics.append({"name": metric, "before": b, "after": a,
                               "changed": not _same(b, a)})
        d.scorers.append(sd)
    return d
