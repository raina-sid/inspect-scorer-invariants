"""inspect-audit: observed differences between two states of an Inspect evaluation.

    inspect-audit snapshot TASK -o before.jsonl [-T key=value ...]
    inspect-audit diff dataset before.jsonl after.jsonl [--json]
    inspect-audit diff scores before.eval after.eval [--json]

Exit status: 0 no differences, 1 differences observed, 2 refused or error. Differences are not
failures; the exit code only lets CI notice them.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from .dataset_diff import diff_datasets
from .render import render_dataset, render_scores
from .score_diff import diff_logs
from .snapshot import Snapshot, snapshot_task


def _task_args(pairs: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for p in pairs:
        if "=" not in p:
            raise SystemExit(f"-T expects key=value, got {p!r}")
        k, v = p.split("=", 1)
        try:
            out[k] = json.loads(v)
        except json.JSONDecodeError:
            out[k] = v
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="inspect-audit", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("snapshot", help="snapshot a task's dataset (no model calls)")
    s.add_argument("task")
    s.add_argument("-o", "--output", required=True)
    s.add_argument("-T", dest="task_args", action="append", default=[])
    d = sub.add_parser("diff", help="diff two states")
    dsub = d.add_subparsers(dest="what", required=True)
    for what, a, b in (("dataset", "before_snapshot", "after_snapshot"),
                       ("scores", "before_log", "after_log")):
        x = dsub.add_parser(what)
        x.add_argument(a)
        x.add_argument(b)
        x.add_argument("--json", action="store_true")
    args = p.parse_args(argv)

    try:
        if args.cmd == "snapshot":
            snap = snapshot_task(args.task, _task_args(args.task_args))
            snap.save(args.output)
            print(f"{len(snap.records):,} samples -> {args.output}", file=sys.stderr)
            return 0
        if args.what == "dataset":
            dd = diff_datasets(Snapshot.load(args.before_snapshot), Snapshot.load(args.after_snapshot))
            print(json.dumps(dd.to_dict(), indent=2) if args.json else render_dataset(dd))
            return 0 if dd.empty else 1
        sd = diff_logs(args.before_log, args.after_log)
        print(json.dumps(sd.to_dict(), indent=2, default=str) if args.json else render_scores(sd))
        return 2 if sd.refused else (0 if sd.empty else 1)
    except Exception as e:  # noqa: BLE001 -- report and exit 2; never pretend success
        print(f"inspect-audit: error: {type(e).__name__}: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
