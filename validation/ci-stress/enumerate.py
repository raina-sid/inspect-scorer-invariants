import subprocess, re, json, collections
def git(*a): return subprocess.run(["git", *a], capture_output=True, text=True).stdout
commits = git("log", "--first-parent", "--since=2026-06-01", "--format=%H %cs", "upstream/main", "--", "src/inspect_evals").split("\n")
rows = []
for line in filter(None, commits):
    c, date = line.split()
    files = git("show", "--name-only", "--format=", c).split()
    evals = sorted({f.split("/")[2] for f in files if f.startswith("src/inspect_evals/") and f.count("/") >= 3})
    for e in evals:
        if e in ("utils", "_registry.py") or e.endswith(".py"): continue
        def ver(ref):
            m = re.search(r'^version:\s*"?([0-9]+)-([A-Z]+)"?', git("show", f"{ref}:src/inspect_evals/{e}/eval.yaml"), re.M)
            return (int(m.group(1)), m.group(2)) if m else None
        a, b = ver(c + "^"), ver(c)
        if a is None or b is None: continue
        label = "N" if b[0] != a[0] else ("X" if b[1] != a[1] else "none")
        code = [f for f in files if f.startswith(f"src/inspect_evals/{e}/") and f.endswith(".py")]
        rows.append({"commit": c[:10], "date": date, "eval": e, "label": label, "py_changed": len(code),
                     "before": f"{a[0]}-{a[1]}", "after": f"{b[0]}-{b[1]}"})
json.dump(rows, open("/tmp/population.json", "w"), indent=1)
c = collections.Counter((r["label"], r["py_changed"] > 0) for r in rows)
print(len(rows), "pairs;", dict(c))
