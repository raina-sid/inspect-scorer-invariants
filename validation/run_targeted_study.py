"""Run the targeted validation study declared in validation/scorer-manifest.yaml.

Each scorer gets a Case set constructed FROM ITS SOURCE, not guessed. The contract for each cell was
frozen in the manifest before this file existed (commit 3d5c263).

    python validation/run_targeted_study.py

Requires inspect_evals importable. Writes targeted-study.json and targeted-study.csv beside itself.
"""

from __future__ import annotations

import csv
import json
import pathlib
import traceback
import warnings
from collections.abc import Callable
from typing import Any

warnings.filterwarnings("ignore")

from inspect_ai.model import ChatMessageAssistant
from inspect_ai.scorer import accuracy, match, mean, stderr
from inspect_ai.tool import ToolCall

from inspect_scorer_probes import Case, Contract, probe
from inspect_scorer_probes.invariants import (
    CODE_FORMATTING,
    CUE_CASE,
    CUE_WHITESPACE,
    MARKUP,
)

HERE = pathlib.Path(__file__).parent

# --------------------------------------------------------------------------------------
# per-scorer setup. Each returns (scorer, metrics, cases, contract, note) or raises.
# --------------------------------------------------------------------------------------


def s_zerobench() -> tuple[Any, Any, list[Case], Contract, str]:
    from inspect_evals.zerobench.scorer import zerobench_scorer

    return (
        zerobench_scorer(),
        {"accuracy": accuracy()},
        [
            Case(completion="Working through it.\nThe answer is {Paris}", target="Paris"),
            Case(completion="Working through it.\nThe answer is {London}", target="Rome"),
        ],
        Contract(invariants=(CUE_CASE, CUE_WHITESPACE), exclusions=(MARKUP,)),
        "answer inside {...}; baseline one correct one incorrect",
    )


def s_threecb() -> tuple[Any, Any, list[Case], Contract, str]:
    from inspect_evals.threecb.threecb import best_elicitation_per_challenge

    return (
        best_elicitation_per_challenge(),
        {"accuracy": accuracy()},
        [
            Case(completion="FLAG{abc123}", target="FLAG{abc123}"),
            Case(completion="FLAG{wrong}", target="FLAG{abc123}"),
        ],
        Contract(invariants=(CUE_WHITESPACE,), exclusions=(CUE_CASE, MARKUP)),
        "bare CTF flag; custom best_per_challenge metric replaced with accuracy for probing",
    )


def s_vqa_rad() -> tuple[Any, Any, list[Case], Contract, str]:
    from inspect_evals.vqa_rad.scorer import vqa_rad_graded_scorer

    closed = {"answer_type": "closed"}
    return (
        vqa_rad_graded_scorer(),
        {"accuracy": accuracy()},
        [
            Case(completion="Looking at it.\nANSWER: yes", target="yes", metadata=dict(closed)),
            Case(completion="Looking at it.\nANSWER: no", target="yes", metadata=dict(closed)),
        ],
        Contract(invariants=(CUE_WHITESPACE, CUE_CASE)),
        "metadata answer_type=closed routes to the exact-match path, not the grader",
    )


def s_aime() -> tuple[Any, Any, list[Case], Contract, str]:
    from inspect_evals.utils.aime_common import aime_scorer

    return (
        aime_scorer(),
        {"accuracy": accuracy(), "stderr": stderr()},
        [
            Case(completion="Some reasoning.\n\\boxed{42}", target="42"),
            Case(completion="Some reasoning.\n\\boxed{7}", target="42"),
        ],
        Contract(invariants=(CUE_WHITESPACE, MARKUP)),
        "last substantive line, boxed answer stripped, numeric match",
    )


def s_core_match() -> tuple[Any, Any, list[Case], Contract, str]:
    return (
        match(numeric=True),
        {"accuracy": accuracy()},
        [
            Case(completion="The answer is 42", target="42"),
            Case(completion="The answer is 7", target="42"),
        ],
        Contract(invariants=(CUE_WHITESPACE, MARKUP)),
        "inspect_ai core numeric match",
    )


def s_tac() -> tuple[Any, Any, list[Case], Contract, str]:
    from inspect_evals.tac.scorer import tac_scorer

    def buy(experience_id: str) -> list[Any]:
        return [
            ChatMessageAssistant(
                content="Booking now.",
                tool_calls=[
                    ToolCall(
                        id="t1",
                        function="purchase_tickets",
                        arguments={"experience_id": experience_id},
                    )
                ],
            )
        ]

    meta = {"harmful_ids": ["harm-1"], "safe_ids": ["safe-1"], "category": "test"}
    return (
        tac_scorer(),
        {"mean": mean()},
        [
            Case(completion="Booking now.", target="", metadata=dict(meta), messages=buy("safe-1")),
            Case(completion="Booking now.", target="", metadata=dict(meta), messages=buy("harm-1")),
        ],
        Contract(invariants=(CUE_WHITESPACE,)),
        "verdict comes from the last purchase_tickets tool call; Score.value is a dict",
    )


def s_bfcl() -> tuple[Any, Any, list[Case], Contract, str]:
    from inspect_evals.bfcl.bfcl import bfcl_scorer

    meta = {"category_name": "irrelevance", "parsed_ground_truth": [], "tools": []}
    called = [
        ChatMessageAssistant(
            content="",
            tool_calls=[ToolCall(id="t1", function="some_tool", arguments={})],
        )
    ]
    return (
        bfcl_scorer(),
        {"accuracy": accuracy()},
        [
            Case(completion="I cannot help with that.", target="", metadata=dict(meta),
                 messages=[ChatMessageAssistant(content="I cannot help with that.")]),
            Case(completion="", target="", metadata=dict(meta), messages=called),
        ],
        Contract(invariants=(CUE_WHITESPACE,)),
        "irrelevance category: correct iff NO tool call was made",
    )


def s_mmiu() -> tuple[Any, Any, list[Case], Contract, str]:
    from inspect_evals.mmiu.mmiu import mmiu_scorer

    return (
        mmiu_scorer(),
        {"accuracy": accuracy()},
        [
            Case(completion="ANSWER: A", target="A", metadata={"task_name": "t"}),
            Case(completion="ANSWER: B", target="A", metadata={"task_name": "t"}),
        ],
        Contract(invariants=(CUE_CASE,)),
        "wraps core choice(), which reads state.choices -- expected abstraction failure",
    )


def s_cyberseceval_4() -> tuple[Any, Any, list[Case], Contract, str]:
    from inspect_evals.cyberseceval_4.instruct_or_autocomplete.scorers import security_scorer

    meta = {"language": "python", "origin_code": "def f():\n    return 1\n"}
    return (
        security_scorer(),
        {"accuracy": accuracy()},
        [
            Case(completion="```python\ndef f():\n    return 1\n```", target="",
                 metadata=dict(meta)),
            Case(completion="```python\nimport os\nos.system(input())\n```", target="",
                 metadata=dict(meta)),
        ],
        Contract(invariants=(CODE_FORMATTING,)),
        "static insecure-code detection; deps semgrep/sacrebleu/codeshield not installed",
    )


def s_make_me_pay() -> tuple[Any, Any, list[Case], Contract, str]:
    from inspect_evals.make_me_pay.scorer import make_me_pay_scorer

    return (
        make_me_pay_scorer(),
        {"mean": mean()},
        [
            Case(completion="Here is my pitch, please donate.", target="",
                 metadata={"donation_amt": 5.0}),
            Case(completion="Here is my pitch, please donate.", target="",
                 metadata={"donation_amt": 0.0}),
        ],
        Contract(invariants=(CUE_WHITESPACE,)),
        "reads only metadata['donation_amt']; the completion is never parsed",
    )


def s_makemesay() -> tuple[Any, Any, list[Case], Contract, str]:
    # constructing a real Game is part of the test: if it cannot be done from the public API the
    # cell is a setup/abstraction failure, recorded as such
    from inspect_evals.makemesay.game import Game, Player  # type: ignore[import-not-found]
    from inspect_evals.makemesay.scorer import makemesay_scorer

    game = Game(
        manipulator=Player(id="m", is_model=True),
        manipulatee=Player(id="u", is_model=True),
        current_player=Player(id="m", is_model=True),
        messages=(),
        word_list=("banana",),
        max_turns=2,
        turn=2,
        internal_monologue_start_token="<",
        internal_monologue_end_token=">",
    )
    return (
        makemesay_scorer(),
        {"accuracy": accuracy()},
        [
            Case(completion="banana", target="", metadata={"game": game, "user_aware": False}),
            Case(completion="banana", target="", metadata={"game": game, "user_aware": True}),
        ],
        Contract(invariants=(CUE_WHITESPACE,)),
        "outcome comes from a Game domain object in metadata",
    )


def s_ape() -> tuple[Any, Any, list[Case], Contract, str]:
    from inspect_evals.ape.scorer import ape_scorer

    return (
        ape_scorer(),
        {"mean": mean()},
        [
            Case(completion="Turn text.", target="",
                 metadata={"turn_scores": [0.8, 0.6], "category": "c", "strongreject_scores": []}),
            Case(completion="Turn text.", target="",
                 metadata={"turn_scores": [], "category": "c", "strongreject_scores": []}),
        ],
        Contract(invariants=(CUE_WHITESPACE,)),
        "metadata-only; deliberately emits NaN when no turn scores exist",
    )


SETUPS: dict[str, Callable[[], tuple[Any, Any, list[Case], Contract, str]]] = {
    "zerobench": s_zerobench,
    "threecb": s_threecb,
    "vqa_rad": s_vqa_rad,
    "aime": s_aime,
    "core_match_numeric": s_core_match,
    "tac": s_tac,
    "bfcl": s_bfcl,
    "mmiu": s_mmiu,
    "cyberseceval_4": s_cyberseceval_4,
    "make_me_pay": s_make_me_pay,
    "makemesay": s_makemesay,
    "ape": s_ape,
}

CATEGORY = {
    "zerobench": "text-extraction", "threecb": "text-extraction", "vqa_rad": "text-extraction",
    "aime": "numeric-equivalence", "core_match_numeric": "numeric-equivalence",
    "tac": "structured", "bfcl": "structured", "mmiu": "structured",
    "cyberseceval_4": "code-format",
    "make_me_pay": "custom-domain", "makemesay": "custom-domain", "ape": "custom-domain",
}


# --------------------------------------------------------------------------------------
# NEGATIVE CONTROLS -- added after the frozen cells, explicitly identified as new cells per the
# study's methodological rule. Each replaces the answer with a GENUINELY DIFFERENT one while the
# declared invariant is EQUAL. A FAIL here is CORRECT behaviour, not a defect: it demonstrates the
# methodology is not demanding invariance everywhere, and that a real change is detected.
# --------------------------------------------------------------------------------------

NEGATIVE_CONTROLS: dict[str, tuple[str, str]] = {
    "zerobench": ("{Paris}", "{Berlin}"),
    "threecb": ("FLAG{abc123}", "FLAG{zzz999}"),
    "vqa_rad": ("ANSWER: yes", "ANSWER: no"),
    "aime": ("\\boxed{42}", "\\boxed{99}"),
    "core_match_numeric": ("is 42", "is 99"),
}


def answer_replaced(old: str, new: str) -> Any:
    from inspect_scorer_probes import transform

    def apply(case: Case) -> Case | None:
        if old not in case.completion:
            return None
        return case.with_completion(case.completion.replace(old, new))

    return transform(f"answer_replaced[{old!r}->{new!r}]", [CUE_WHITESPACE], ["completion"], apply)


def run_negative_controls(rows: list[dict[str, Any]]) -> None:
    for sid, (old, new) in NEGATIVE_CONTROLS.items():
        try:
            scorer_obj, metrics, cases, _contract, _note = SETUPS[sid]()
            report = probe(
                scorer_obj, metrics, cases,
                Contract(invariants=(CUE_WHITESPACE,)),
                transforms=[answer_replaced(old, new)],
            )
        except Exception as exc:
            rows.append({
                "scorer": sid, "category": CATEGORY[sid], "cell_type": "negative_control",
                "invariant": "CUE_WHITESPACE", "transformation": "answer_replaced",
                "outcome": "SETUP_FAILED", "detail": f"{type(exc).__name__}: {exc}"[:200],
            })
            continue
        r = next((x for x in report.results if x.transformation.startswith("answer_replaced")), None)
        if r is None:
            rows.append({
                "scorer": sid, "category": CATEGORY[sid], "cell_type": "negative_control",
                "invariant": "CUE_WHITESPACE", "transformation": "answer_replaced",
                "outcome": "NOT_RUN", "detail": "transformation not applied",
            })
            continue
        rows.append({
            "scorer": sid, "category": CATEGORY[sid], "cell_type": "negative_control",
            "invariant": r.invariant, "transformation": r.transformation,
            "outcome": r.outcome.name, "layers": "+".join(r.layers),
            "cases_transformed": f"{r.cases_transformed}/{r.cases_total}",
            "baseline_verdicts": str(list(report.baseline_verdicts)),
            "transformed_verdicts": str([c.after for c in r.verdicts]),
            "baseline_metrics": str(dict(report.baseline_metrics)),
            "transformed_metrics": str({m.name: m.after for m in r.metrics}),
            "detail": " | ".join(r.details)[:300],
            "note": f"NEGATIVE CONTROL: {old!r} -> {new!r} is a different answer; FAIL is correct",
        })


def main() -> None:
    rows: list[dict[str, Any]] = []
    for sid, setup in SETUPS.items():
        try:
            scorer_obj, metrics, cases, contract, note = setup()
        except Exception as exc:
            rows.append({
                "scorer": sid, "category": CATEGORY[sid], "invariant": "-",
                "transformation": "-", "outcome": "SETUP_FAILED",
                "detail": f"{type(exc).__name__}: {exc}"[:260],
                "baseline_verdicts": "", "transformed_verdicts": "",
                "baseline_metrics": "", "transformed_metrics": "", "note": "",
            })
            continue

        try:
            report = probe(scorer_obj, metrics, cases, contract, scorer_source=None)
        except Exception as exc:
            rows.append({
                "scorer": sid, "category": CATEGORY[sid], "invariant": "-",
                "transformation": "-", "outcome": "PROBE_RAISED",
                "detail": f"{type(exc).__name__}: {exc}\n{traceback.format_exc(limit=2)}"[:400],
                "baseline_verdicts": "", "transformed_verdicts": "",
                "baseline_metrics": "", "transformed_metrics": "", "note": note,
            })
            continue

        base_v = list(report.baseline_verdicts)
        base_m = dict(report.baseline_metrics)
        for r in report.results:
            after_v = [c.after for c in r.verdicts] if r.verdicts else []
            after_m = {m.name: m.after for m in r.metrics} if r.metrics else {}
            rows.append({
                "scorer": sid,
                "category": CATEGORY[sid],
                "invariant": r.invariant,
                "transformation": r.transformation,
                "outcome": r.outcome.name,
                "layers": "+".join(r.layers),
                "cases_transformed": f"{r.cases_transformed}/{r.cases_total}",
                "detail": " | ".join(r.details)[:400],
                "baseline_verdicts": str(base_v),
                "transformed_verdicts": str(after_v),
                "baseline_metrics": str(base_m),
                "transformed_metrics": str(after_m),
                "baseline_notes": " | ".join(report.baseline_notes),
                "note": note,
            })

    for r in rows:
        r.setdefault("cell_type", "declared")
    run_negative_controls(rows)

    (HERE / "targeted-study.json").write_text(json.dumps(rows, indent=1, default=str))
    fields = sorted({k for r in rows for k in r})
    with (HERE / "targeted-study.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow(r)

    print(f"{'scorer':20} {'type':17} {'invariant':16} {'transformation':26} outcome")
    print("-" * 104)
    for r in rows:
        print(f"{r['scorer']:20} {r.get('cell_type','declared'):17} {r['invariant']:16} "
              f"{r['transformation'][:26]:26} {r['outcome']}")
    print("-" * 92)
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["outcome"]] = counts.get(r["outcome"], 0) + 1
    print("  " + "  ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    print(f"  cells recorded: {len(rows)}  scorers: {len(SETUPS)}")


main()
