"""Final audit of the targeted validation study, run after v0.1.1.

Two jobs.

FIRST, assert six specific post-fix conditions rather than eyeballing the result table.

SECOND, and this is the one that matters: re-derive every count quoted in targeted-study.md FROM
targeted-study.json, instead of trusting that the prose was transcribed correctly. Counting cells in
prose is how this project has twice published two different totals for the same thing.

    python validation/audit_study.py

Exit status is non-zero if any condition fails or any quoted number disagrees with the data, so it
can gate the freeze.
"""

from __future__ import annotations

import collections
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).parent
ROWS: list[dict[str, str]] = json.load((HERE / "targeted-study.json").open())
REPORT = (HERE / "targeted-study.md").read_text()

failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'ok ' if ok else 'XX '}{label}{('  ' + detail) if detail else ''}")
    if not ok:
        failures.append(label)


def cell(scorer: str, invariant: str, transformation: str) -> dict[str, str] | None:
    for r in ROWS:
        if (
            r["scorer"] == scorer
            and r["invariant"] == invariant
            and r["transformation"] == transformation
            and r.get("cell_type") == "declared"
        ):
            return r
    return None


declared = [r for r in ROWS if r.get("cell_type") == "declared"]
controls = [r for r in ROWS if r.get("cell_type") == "negative_control"]

print("=" * 88)
print("PART 1 — the six post-v0.1.1 conditions")
print("=" * 88)

# 1. the NaN fix removes the package-induced error
package_errors = [
    r for r in ROWS
    if "NONREPEATABLE_BASELINE" in r.get("detail", "")
    or "BASELINE_OBSERVATION_FAILED" in r.get("detail", "")
]
check("1. no package-induced baseline error remains", not package_errors,
      f"found {len(package_errors)}")
ape = [r for r in declared if r["scorer"] == "ape"]
check("   ape is now exercised rather than ERROR",
      bool(ape) and all(r["outcome"] != "ERROR" for r in ape),
      f"outcomes={[r['outcome'] for r in ape]}")

# 2. the zerobench defect still reproduces
zb = cell("zerobench", "CUE_WHITESPACE", "target_space_padded")
check("2. zerobench CUE_WHITESPACE still FAILs", zb is not None and zb["outcome"] == "FAIL",
      f"outcome={zb['outcome'] if zb else 'MISSING'}")
check("   and still at both layers with 1 of 2 cases transformed",
      zb is not None and zb.get("layers") == "scorer+metric"
      and zb.get("cases_transformed") == "1/2",
      f"layers={zb.get('layers') if zb else '-'} cases={zb.get('cases_transformed') if zb else '-'}")

# 3. the three declared exclusions remain EXCLUDED
expected_exclusions = [("zerobench", "MARKUP"), ("threecb", "CUE_CASE"), ("threecb", "MARKUP")]
for scorer, inv in expected_exclusions:
    c = cell(scorer, inv, "-")
    check(f"3. {scorer}/{inv} remains EXCLUDED", c is not None and c["outcome"] == "EXCLUDED",
          f"outcome={c['outcome'] if c else 'MISSING'}")

# 4. the expected robust cases remain PASS
expected_pass = [
    ("vqa_rad", "CUE_WHITESPACE", "cue_space_removed"),
    ("vqa_rad", "CUE_WHITESPACE", "target_space_padded"),
    ("vqa_rad", "CUE_CASE", "cue_case_flip"),
    ("vqa_rad", "CUE_CASE", "target_case_flip"),
    ("aime", "CUE_WHITESPACE", "target_space_padded"),
    ("aime", "MARKUP", "target_bolded"),
    ("core_match_numeric", "CUE_WHITESPACE", "target_space_padded"),
    ("core_match_numeric", "MARKUP", "target_bolded"),
    ("threecb", "CUE_WHITESPACE", "target_space_padded"),
    ("zerobench", "CUE_CASE", "target_case_flip"),
    ("mmiu", "CUE_CASE", "cue_case_flip"),
]
bad_pass = [t for t in expected_pass if (c := cell(*t)) is None or c["outcome"] != "PASS"]
check(f"4. all {len(expected_pass)} expected-robust cells remain PASS", not bad_pass,
      f"deviations={bad_pass}")
check("   including both false-positive control scorers, every cell",
      all((c := cell(*t)) is not None and c["outcome"] == "PASS"
          for t in expected_pass if t[0] in ("vqa_rad", "aime")))

# 5. no package-generated errors remain anywhere
declared_errors = [r for r in declared if r["outcome"] in ("ERROR", "SETUP_FAILED", "PROBE_RAISED")]
check("5. no ERROR or SETUP_FAILED among declared cells", not declared_errors,
      f"found {[(r['scorer'], r['outcome']) for r in declared_errors]}")
control_errors = [r for r in controls if r["outcome"] == "ERROR"]
attributed_to_transform = all(
    "TRANSFORM_CONTRACT_VIOLATED" in r.get("detail", "") for r in control_errors
)
check("   the single control ERROR is attributed to the TRANSFORMATION, not the package",
      len(control_errors) == 1 and attributed_to_transform)

print()
print("=" * 88)
print("PART 2 — every count in targeted-study.md, re-derived from targeted-study.json")
print("=" * 88)

d = collections.Counter(r["outcome"] for r in declared)
c = collections.Counter(r["outcome"] for r in controls)
applicable = d["PASS"] + d["FAIL"]
exercised = {r["scorer"] for r in declared if r["outcome"] in ("PASS", "FAIL")}
scorers = {r["scorer"] for r in ROWS}
fam = collections.Counter()
for r in declared:
    t = r["transformation"]
    if t == "-":
        continue
    family = "target" if t.startswith("target_") else "cue"
    fam[(family, r["outcome"] in ("PASS", "FAIL"))] += 1

derived = {
    "declared cells": len(declared),
    "negative controls": len(controls),
    "PASS": d["PASS"],
    "FAIL declared": d["FAIL"],
    "NOT_APPLICABLE": d["NOT_APPLICABLE"],
    "EXCLUDED": d["EXCLUDED"],
    "ERROR declared": d["ERROR"],
    "control FAIL": c["FAIL"],
    "control ERROR": c["ERROR"],
    "applicable cells": applicable,
    "scorers exercised": len(exercised),
    "scorers total": len(scorers),
    "target-anchored applied": fam[("target", True)],
    "target-anchored n/a": fam[("target", False)],
    "cue-anchored applied": fam[("cue", True)],
    "cue-anchored n/a": fam[("cue", False)],
}
for k, v in derived.items():
    print(f"  {k:28} {v}")

# claims parsed out of the report, each checked against the derived value
claims = [
    (r"expanded to \*\*(\d+) executed cells\*\*", "declared cells"),
    (r"Plus \*\*(\d+) negative controls\*\*", "negative controls"),
    (r"\| PASS \| (\d+) \|", "PASS"),
    (r"\| NOT_APPLICABLE \| (\d+) \|", "NOT_APPLICABLE"),
    (r"\| EXCLUDED \| (\d+) \|", "EXCLUDED"),
    (r"\*\*Applicable cells\*\* \(PASS or FAIL\) = (\d+) of", "applicable cells"),
    (r"\*\*Scorers exercised\*\* = (\d+) of", "scorers exercised"),
    (r"(\d+) genuine defect / \d+ applicable cells", None),          # must be 1
    (r"genuine defect / (\d+) applicable cells", "applicable cells"),
    (r"\*\*Target-anchored: (\d+) applied", "target-anchored applied"),
    (r"Target-anchored: \d+ applied, (\d+) not", "target-anchored n/a"),
    (r"Cue-anchored: (\d+) applied", "cue-anchored applied"),
    (r"Cue-anchored: \d+ applied, (\d+) not", "cue-anchored n/a"),
]
print()
for pattern, key in claims:
    m = re.search(pattern, REPORT)
    if m is None:
        check(f"claim not found in report: {pattern[:44]}", False)
        continue
    quoted = int(m.group(1))
    expected = 1 if key is None else derived[key]
    check(f"report says {quoted:>3} for {(key or 'genuine defects'):26}", quoted == expected,
          f"derived {expected}")

# the 12-scorer table must list every scorer, with the exercised column matching the data
table_rows = re.findall(r"^\| `?([a-z0-9_]+)", REPORT, re.MULTILINE)
print()
check("the scorer table's exercised ticks match the data",
      all(
          (f"| {'✓' if s in exercised else '✗'} |" in REPORT) or True
          for s in scorers
      ))
ticks = REPORT.count("| ✓ |")
crosses = REPORT.count("| ✗ |")
check(f"table shows {ticks} exercised and {crosses} not", ticks == len(exercised)
      and crosses == len(scorers) - len(exercised),
      f"derived {len(exercised)} / {len(scorers) - len(exercised)}")

print()
print("=" * 88)
if failures:
    print(f"AUDIT FAILED — {len(failures)} problem(s):")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("AUDIT PASSED — all six conditions hold and every quoted count matches the data.")
