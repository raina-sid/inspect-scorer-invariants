"""The applicability census: what fraction of real scorers this package can even reach.

This is the coverage claim, and it is deliberately unflattering. It records the 18 evals attempted
during the pre-registered run of 2026-09-21, and why each one could or could not be probed.

The honest headline is that fewer than half were exercisable, and the reasons are structural rather
than fixable: a scorer that needs a judge model is not repeatable, a scorer that needs a sandbox
cannot run offline, a scorer whose grading logic lives in an upstream pip package is not present,
and a scorer that reads its answer from a file rather than from model prose has no text cue to
perturb.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Reach(Enum):
    #: at least one probe produced a PASS or a FAIL
    EXERCISABLE = "exercisable"
    #: the scorer calls a grader model, so the baseline is not repeatable
    BLOCKED_JUDGE = "blocked_judge"
    #: the scorer needs a container
    BLOCKED_SANDBOX = "blocked_sandbox"
    #: the grading logic lives in an upstream pip package, not in the eval repo
    BLOCKED_UPSTREAM = "blocked_upstream"
    #: reachable, but no frozen transformation can be expressed against it
    NO_SURFACE = "no_surface"


@dataclass(frozen=True)
class Entry:
    eval_name: str
    reach: Reach
    note: str


CENSUS: tuple[Entry, ...] = (
    Entry("agieval", Reach.EXERCISABLE, "cue extraction; whitespace and prefix probes applied"),
    Entry("scbench", Reach.EXERCISABLE, "answer read from eval_answer.json; most probes N-A"),
    Entry("frontierscience", Reach.EXERCISABLE, "VERDICT cue; markup contract-excluded"),
    Entry("worldsense", Reach.EXERCISABLE, "FAIL at the metric layer"),
    Entry("novelty_bench", Reach.EXERCISABLE, "FAIL on markup; passes case and whitespace"),
    Entry("tau2", Reach.EXERCISABLE, "FAIL on an unanchored substring test"),
    Entry("gpqa", Reach.EXERCISABLE, "control: core choice(); markup is a core property"),
    Entry("hellaswag", Reach.EXERCISABLE, "control: core choice()"),
    Entry("truthfulqa", Reach.EXERCISABLE, "control: core choice()"),
    Entry("moru", Reach.BLOCKED_JUDGE, "grader model required"),
    Entry("persistbench", Reach.BLOCKED_JUDGE, "grader model required"),
    Entry("mask", Reach.BLOCKED_JUDGE, "binary and numeric judge models required"),
    Entry("instrumentaleval", Reach.BLOCKED_JUDGE, "grader_model is a required argument"),
    Entry("gdm_self_proliferation", Reach.BLOCKED_SANDBOX, "sandbox exec required"),
    Entry("livebench", Reach.BLOCKED_UPSTREAM, "all 14 graders imported from the livebench package"),
    Entry("kernelbench", Reach.BLOCKED_UPSTREAM, "kernelbench package, torch and CUDA required"),
    Entry("bfcl", Reach.NO_SURFACE, "structural tool-call matching; no prose cue to perturb"),
    Entry("vimgolf_challenges", Reach.NO_SURFACE, "prompt forbids fences and markup outright"),
)


def counts() -> dict[str, int]:
    out = {r.value: 0 for r in Reach}
    for entry in CENSUS:
        out[entry.reach.value] += 1
    return out


def summary() -> str:
    tally = counts()
    total = len(CENSUS)
    lines = [f"Applicability census: {total} evals attempted (pre-registered run, 2026-09-21)", ""]
    for reach in Reach:
        lines.append(f"  {reach.value:<18} {tally[reach.value]:>2}")
    lines.append("")
    reached = tally[Reach.EXERCISABLE.value]
    lines.append(f"  exercisable: {reached}/{total} ({100 * reached // total}%)")
    lines.append("")
    lines.append("  Defects found: 3, on 3 different scorer types (worldsense, novelty_bench, tau2)")
    lines.append("  Not a recall estimate: these probes are what found them.")
    return "\n".join(lines)


if __name__ == "__main__":
    print(summary())
