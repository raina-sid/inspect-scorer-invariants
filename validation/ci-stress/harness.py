"""CI stress-test harness. Pre-registration: PREREG.md in this directory.

    python validation/ci-stress/harness.py [--limit N]

For each (commit, eval) pair: extract the minimal source for the eval at parent and at commit, build
each task's dataset in a fresh process with that source first on sys.path, snapshot it, and diff.
The commit side is built twice to measure flakiness. No API keys are set, so nothing can call a model.
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = "/tmp/iefork"
HERE = Path(__file__).parent
WORK = Path("/tmp/stress/work")          # everything this harness creates and deletes lives here
OUT = Path("/tmp/stress/out")
PY = sys.executable
TIMEOUT = 300
MAX_TASKS = 5
MIN_FREE_BYTES = 15e9   # stop cleanly below this; a full disk corrupted 3 pairs on the first run

WORKER = r'''
import json, sys, warnings, importlib, inspect as pi
warnings.filterwarnings("ignore")
src, eval_name, task_names, out = sys.argv[1], sys.argv[2], json.loads(sys.argv[3]), sys.argv[4]
sys.path.insert(0, src)
import inspect_evals
if not inspect_evals.__file__.startswith(src):
    print(json.dumps({"fatal": f"imported inspect_evals from {inspect_evals.__file__}, not {src}"})); sys.exit(3)
importlib.import_module(f"inspect_evals.{eval_name}")
from inspect_ai._util.registry import registry_lookup
from inspect_audit.snapshot import Snapshot, records_from_samples
res = {}
for t in task_names:
    try:
        fn = registry_lookup("task", f"inspect_evals/{t}")
        if fn is None:
            res[t] = {"error": "task not registered"}; continue
        args = {"shuffle": False} if "shuffle" in pi.signature(fn).parameters else {}
        task = fn(**args)
        snap = Snapshot(task=t, records=records_from_samples(task.dataset),
                        info={"shuffle_disabled": bool(args)})
        path = f"{out}/{t}.jsonl"; snap.save(path)
        res[t] = {"n": len(snap.records), "path": path, "shuffle_disabled": bool(args)}
    except Exception as e:
        res[t] = {"error": f"{type(e).__name__}: {str(e)[:200]}"}
print(json.dumps(res))
'''


def git(*a: str) -> str:
    return subprocess.run(["git", "-C", REPO, *a], capture_output=True, text=True, check=False).stdout


def tasks_of(ref: str, ev: str) -> list[str]:
    y = git("show", f"{ref}:src/inspect_evals/{ev}/eval.yaml")
    return re.findall(r"^\s*-\s*name:\s*\"?([A-Za-z0-9_]+)\"?", y, re.M)[:MAX_TASKS]


def extract(ref: str, ev: str, dest: Path, extra: set[str]) -> None:
    top = [p for p in git("ls-tree", "--name-only", ref, "src/inspect_evals/").split()
           if p.endswith(".py")]
    paths = top + [f"src/inspect_evals/{d}" for d in {"utils", ev, *extra}]
    paths = [p for p in paths if git("ls-tree", "--name-only", ref, p).strip()]
    dest.mkdir(parents=True, exist_ok=True)
    arch = subprocess.run(["git", "-C", REPO, "archive", ref, *paths], capture_output=True,
                          check=False)
    subprocess.run(["tar", "-x", "-C", str(dest)], input=arch.stdout, check=True)


def build(ref: str, ev: str, tasks: list[str], label: str, cache: Path) -> tuple[dict, float]:
    t0 = time.time()
    extra: set[str] = set()
    full = False
    for _attempt in range(8):
        d = Path(tempfile.mkdtemp(dir=WORK))
        out = d / "snap"; out.mkdir()
        try:
            if full:  # an eval (or utils) that imports across the whole package: take all of src
                arch = subprocess.run(["git", "-C", REPO, "archive", ref, "src"], capture_output=True,
                                      check=False)
                subprocess.run(["tar", "-x", "-C", str(d)], input=arch.stdout, check=True)
            else:
                extract(ref, ev, d, extra)
            # Per-pair caches, deleted after the pair: the first run filled the disk with 48 GB of
            # datasets in one shared cache.
            env = {**{k: v for k, v in os.environ.items() if "API_KEY" not in k},
                   "HF_HOME": str(cache / "hf"), "INSPECT_EVALS_CACHE_DIR": str(cache / "ie")}
            p = subprocess.run([PY, "-c", WORKER, str(d / "src"), ev, json.dumps(tasks), str(out)],
                               cwd=d, capture_output=True, text=True, timeout=TIMEOUT, env=env)
            missing = re.search(r"No module named '?inspect_evals\.([A-Za-z0-9_]+)", p.stderr + p.stdout)
            if missing and not full and missing.group(1) != ev:
                if len(extra) >= 3:
                    full = True
                else:
                    extra.add(missing.group(1))
                shutil.rmtree(d); continue
            try:
                res = json.loads(p.stdout.strip().splitlines()[-1])
            except Exception:
                res = {"fatal": (p.stderr.strip().splitlines() or ["no output"])[-1][:300]}
            # keep the snapshots, move them out of the work dir
            keep = OUT / "snaps" / f"{ref[:10]}_{ev}_{label}"
            if keep.exists(): shutil.rmtree(keep)
            shutil.copytree(out, keep)
            for v in res.values() if isinstance(res, dict) else []:
                if isinstance(v, dict) and "path" in v:
                    v["path"] = str(keep / Path(v["path"]).name)
            shutil.rmtree(d)
            if isinstance(res, dict):
                res["_full_checkout"] = full
            return res, time.time() - t0
        except subprocess.TimeoutExpired:
            shutil.rmtree(d, ignore_errors=True)
            return {"fatal": "TIMEOUT"}, time.time() - t0
    return {"fatal": f"unresolved imports {sorted(extra)}"}, time.time() - t0


def diff(a: str, b: str) -> dict:
    from inspect_audit import Snapshot, diff_datasets
    d = diff_datasets(Snapshot.load(a), Snapshot.load(b)).to_dict()
    d["groups"] = d["groups"][:15]
    return d


def run_pair(pair: dict) -> dict:
    f = OUT / "pairs" / f"{pair['commit']}_{pair['eval']}.json"
    if f.exists():
        return json.loads(f.read_text())
    if shutil.disk_usage("/tmp").free < MIN_FREE_BYTES:
        return {**pair, "fatal": "SKIPPED_LOW_DISK"}      # not written: the pair stays resumable
    cache = WORK / f"cache_{pair['commit']}_{pair['eval']}"
    c = git("rev-parse", pair["commit"]).strip()
    tasks = tasks_of(c, pair["eval"])
    r = {**pair, "tasks": tasks}
    if not tasks:
        r["fatal"] = "no tasks listed in eval.yaml"
    else:
        try:
            before, tb = build(c + "^", pair["eval"], tasks, "before", cache)
            after, ta = build(c, pair["eval"], tasks, "after", cache)
            again, tc = build(c, pair["eval"], tasks, "again", cache)
        finally:
            shutil.rmtree(cache, ignore_errors=True)
        r.update(secs={"before": round(tb, 1), "after": round(ta, 1), "again": round(tc, 1)},
                 build={"before": before, "after": after, "again": again}, diffs={}, flake={})
        for t in tasks:
            b, a, g = (x.get(t, {}) if isinstance(x, dict) else {} for x in (before, after, again))
            b, a, g = (x if isinstance(x, dict) else {} for x in (b, a, g))
            if "path" in b and "path" in a:
                r["diffs"][t] = diff(b["path"], a["path"])
            if "path" in a and "path" in g:
                r["flake"][t] = not diff(a["path"], g["path"])["empty"]
    f.write_text(json.dumps(r, indent=1, default=str))
    return r


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--only", default="")
    args = ap.parse_args()
    for p in (WORK, OUT / "pairs", OUT / "snaps"):
        p.mkdir(parents=True, exist_ok=True)
    pop = json.loads((HERE / "population.json").read_text())
    primary = [p for p in pop if p["py_changed"] > 0]
    docs = [p for p in pop if p["py_changed"] == 0 and p["label"] == "none"]
    controls = random.Random(0).sample(docs, 40)
    for p in controls:
        p["control"] = True
    todo = primary + controls
    if args.only:
        todo = [p for p in todo if f"{p['commit']}_{p['eval']}" == args.only]
    if args.limit:
        todo = todo[: args.limit]
    print(f"{len(todo)} pairs", flush=True)
    with cf.ThreadPoolExecutor(4) as ex:
        for i, r in enumerate(ex.map(run_pair, todo)):
            print(i, r["commit"], r["eval"], r["label"], "fatal" if "fatal" in r else
                  {t: ("EMPTY" if d["empty"] else "DIFF") for t, d in r.get("diffs", {}).items()},
                  flush=True)


if __name__ == "__main__":
    main()
