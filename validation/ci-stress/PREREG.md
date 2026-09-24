# Can `inspect-audit diff` work as a CI differential regression check? — PRE-REGISTRATION

Written 2026-09-24 BEFORE any pair in the population was built. Upstream inspect_evals `e3402e36c`.

## Why this design
A CI check is only worth running if it (1) builds, (2) does not flake, (3) is mostly quiet when
nothing comparability-relevant changed, and (4) sometimes says something a reviewer did not know.
Ground truth for (3)-(4) is the MAINTAINERS' OWN DECLARATION, made without this tool: every eval has
a version `N-X` and TASK_VERSIONING.md requires an N bump for comparability-breaking changes, an X bump
for interface-only changes.

## Population (fixed; `population.json`, built by `enumerate.py`)
Every (first-parent commit, eval) pair on upstream main since 2026-06-01 where the eval's
`eval.yaml` exists at both parent and commit: 723 pairs.
- Primary: the 166 pairs that changed the eval's Python — declared N 66, X 23, none 77.
- Controls: 40 docs-only pairs (no .py changed, label none), sampled with `random.Random(0)`.
Each pair: every task listed in the eval's eval.yaml at the commit, capped at 5 tasks, default args
(shuffle=False where accepted). Pairs whose dataset cannot be built (gated, extras, sandbox, network
failure, missing file) are RECORDED as build failures, not dropped.

Score diffs are NOT tested: upstream stores only header-only logs, so there are no transcripts to
re-score. That is a finding about CI viability in its own right, stated here before running.

## Measures
M1 build success: fraction of pairs where both sides build.
M2 flake: every buildable task at the commit built TWICE in independent processes; any non-empty
   diff is a flake.
M3 fire rate by label: fraction of buildable pairs with a non-empty dataset diff, for N / X / none /
   docs-only.
M4 reading: EVERY non-empty diff on X, none and docs-only pairs is read against the PR and classified
   (a) tool noise — the dataset did not actually change as reported;
   (b) undeclared change — a real change to the evaluated samples with no N bump;
   (c) consistent — a real change the declaration accounts for (e.g. metadata-only under an X bump).
   For N-bump pairs: tally empty/non-empty, and read 10 non-empty ones to check the diff describes
   what the PR says it changed.
M5 wall time per pair (median, p90) and per snapshot.

## Criteria for "usable as a CI check" (all must hold)
C1 flake rate <= 1% of buildable tasks.
C2 tool noise (a) <= 5% of non-empty diffs on X / none / docs-only pairs.
C3 median pair wall time <= 5 minutes.
C4 build success >= 70% of primary pairs.
## Criterion for "adds value beyond the declaration"
V1 at least one (b) undeclared change on X / none pairs. Prediction: ~40% chance.

## Predictions
- Most N bumps are scorer or solver changes, so most N-bump pairs will have an EMPTY dataset diff;
  guess 60-80% empty. That is not a miss: it bounds what a dataset diff can see, and says how much
  of comparability risk would need score diffs (which upstream cannot run today).
- docs-only controls: 0 non-empty, else tool noise.
- The main risk to C1 is tasks that shuffle or sample without exposing a `shuffle` argument.
