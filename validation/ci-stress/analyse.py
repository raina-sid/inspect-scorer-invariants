"""Aggregate the CI stress run into the pre-registered measures M1-M5. Reads /tmp/stress/out/pairs.

    python validation/ci-stress/analyse.py [--read]    # --read prints every diff that must be read
"""

from __future__ import annotations

import argparse
import collections
import json
import statistics
from pathlib import Path

PAIRS = Path("/tmp/stress/out/pairs")


def load() -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted(PAIRS.glob("*.json"))]


def kind(r: dict) -> str:
    return "docs" if r.get("control") else r["label"]


def built(r: dict) -> bool:
    return bool(r.get("diffs"))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--read", action="store_true")
    args = ap.parse_args()
    rs = [r for r in load() if r.get("label") != "pilot"]
    by = collections.defaultdict(list)
    for r in rs:
        by[kind(r)].append(r)

    print(f"pairs run: {len(rs)}")
    print("\nM1 build success (both sides built at least one task)")
    for k in ("N", "X", "none", "docs"):
        g = by.get(k, [])
        print(f"  {k:5} {sum(built(r) for r in g):4} / {len(g):4}")
    prim = [r for r in rs if not r.get("control")]
    print(f"  primary overall {sum(built(r) for r in prim)} / {len(prim)} "
          f"({sum(built(r) for r in prim) / max(1, len(prim)):.0%})")

    fails = collections.Counter()
    for r in rs:
        if "fatal" in r:
            fails[r["fatal"][:60]] += 1
        for side in ("before", "after"):
            b = r.get("build", {}).get(side, {})
            if isinstance(b, dict) and "fatal" in b:
                fails[f"{side}: {b['fatal'][:60]}"] += 1
            elif isinstance(b, dict):
                for t, x in b.items():
                    if isinstance(x, dict) and "error" in x:
                        fails[f"{side} task: {x['error'][:60]}"] += 1
    print("  top build failures:")
    for f, n in fails.most_common(10):
        print(f"    {n:4}  {f}")

    tasks = [(r, t) for r in rs for t in r.get("flake", {})]
    flaky = [(r, t) for r, t in tasks if r["flake"][t]]
    print(f"\nM2 flake: {len(flaky)} / {len(tasks)} buildable tasks "
          f"({len(flaky) / max(1, len(tasks)):.1%})")
    for r, t in flaky:
        print(f"    FLAKE {r['commit']} {r['eval']}/{t}")

    print("\nM3 fire rate (pair has >= 1 task with a non-empty diff)")
    for k in ("N", "X", "none", "docs"):
        g = [r for r in by.get(k, []) if built(r)]
        fired = [r for r in g if any(not d["empty"] for d in r["diffs"].values())]
        print(f"  {k:5} {len(fired):4} / {len(g):4}  ({len(fired) / max(1, len(g)):.0%})")

    secs = [sum(r["secs"].values()) for r in rs if "secs" in r]
    if secs:
        q = statistics.quantiles(secs, n=10)
        print(f"\nM5 wall time per pair (3 builds): median {statistics.median(secs):.0f}s, "
              f"p90 {q[-1]:.0f}s, max {max(secs):.0f}s")

    if args.read:
        print("\n==== EVERY non-empty diff on X / none / docs pairs (M4 reading list) ====")
        for k in ("X", "none", "docs"):
            for r in by.get(k, []):
                for t, d in r.get("diffs", {}).items():
                    if d["empty"]:
                        continue
                    s = d["samples"]
                    print(f"\n[{k}] {r['commit']} {r['date']} {r['eval']}/{t}  version "
                          f"{r['before']}->{r['after']}")
                    print(f"   samples {s}")
                    for g in d["groups"][:6]:
                        print(f"   group {g['key']}={g['value'][:40]}: {g['before']} -> {g['after']}")
                    for c, ids in d["examples"].items():
                        print(f"   e.g. {c}: {ids[:3]}")


if __name__ == "__main__":
    main()
