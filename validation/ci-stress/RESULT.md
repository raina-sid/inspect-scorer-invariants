# Can `inspect-audit diff` work as a CI check? — result

Pre-registration: [`PREREG.md`](PREREG.md) (commit 82d8b2d). Per-pair data: [`pairs/`](pairs/),
aggregate: [`analyse-output.txt`](analyse-output.txt), produced by [`analyse.py`](analyse.py) over
[`harness.py`](harness.py).

## Verdict: not as a CI gate. Useful for one-shot audits.

Stopped deliberately after 119 of the 206 planned pairs. The remaining pairs and the 40 docs-only
controls were **not run**. The reasons for not finishing are in "Why stopped" below: what was measured
already answers the question, and more pairs would refine the numbers without changing the answer.

## Against the pre-registered criteria (119 pairs, commits 2026-06-01 .. 2026-09-23)

| | criterion | observed | |
|---|---|---|---|
| C1 | flake <= 1% of buildable tasks | **8 / 133 (6.0%)** | fail |
| C2 | tool noise <= 5% of non-empty diffs on X / none / docs | 0 tool noise; see note | pass as defined |
| C3 | median pair time <= 5 min | median 9 s, p90 42 s, max 105 s (3 builds) | pass |
| C4 | build success >= 70% of primary pairs | **64 / 119 (54%)** | fail |
| V1 | >= 1 undeclared change on X / none pairs | **0** | not met |

**Note on C2.** No diff misreported a dataset. But all 7 non-empty diffs on X / none pairs came from
datasets that are **different on every build of identical code** (below). A CI user would experience
them as noise even though the tool read them correctly.

## Every non-empty diff, read

| pair | declared | what it is |
|---|---|---|
| `6c97e3589` #2041, gpqa_diamond + 5 sad tasks | none | non-deterministic construction: answer choices shuffled without a seed |
| `81edb2765` #2442, cyse2_vulnerability_exploit | X | non-deterministic construction: randomised challenge generation |
| `700904dde` #2393, gpqa_diamond | N | "seed the answer-choice shuffle so every build is the same exam" — declared |
| `a89ec0318` #2422, agent_bench_os | N | "repair the OS test split ground truth": 42 removed, 36 added — declared |
| `b91aa2464` #2390, mind2web_sc | N | "load full 200 samples": 10 -> 200 — declared |

Every real change the diff saw had already been declared by its author with an N bump. 0 undeclared in
64 buildable pairs does not show there are none. It does bound the rate as low, roughly under 5% of
pairs.

## Why builds failed (C4)

Top causes, both sides: the task constructs a model or API client at build time and no key was set
(the harness runs without keys, as a CI job would); `docker compose` required; `torch` or other extras
not installed. **The evals the diff cannot build are disproportionately the agentic, model-graded and
sandboxed ones, which is where comparability risk is most likely.**

Score diffs were not testable at all: upstream stores only header-only logs, so there are no
transcripts to re-score (stated in the pre-registration).

## What building twice found (the one live result)

Building the SAME code twice at HEAD `e3402e36c` (`determinism/`):

| task | samples differing between two builds |
|---|---|
| sad_stages_full | 766 / 800 |
| sad_facts_llms | 126 / 249 |
| cyse2_vulnerability_exploit | 534 / 585 |
| gpqa_diamond | 0 (seeded by #2393; positive control) |

`sad`'s dataset loader documents it: `seed=None` means "shuffling is non-deterministic". The
maintainers fixed exactly this in gpqa (#2393) with an N bump, treating it as comparability-breaking.
No upstream report was found for sad or cyse2. **Not yet checked:** whether the benchmarks' reference
implementations shuffle the same way. That check is required before calling this a port defect.

## Deviations from the pre-registration

- The disk filled twice. The first time, a shared dataset cache reached 48 GB. The second time,
  `mind2web`'s download reached 34 GB inside one pair's cache, while four pairs ran concurrently. The
  harness gained per-pair caches, a disk guard and a full-checkout fallback mid-run. These changed how
  datasets were built, not what was measured. 15 pairs damaged or blocked by the first run were
  quarantined and re-run.
- The first run's "unresolved imports" failures were a harness artefact (minimal extraction); those
  pairs were re-run from a full checkout.
- The docs-only controls come after the primary pairs in run order and were never reached.

## Implications, stated once

As a CI gate it would be silent almost always. When it spoke, it would mostly confirm what the PR
author had already declared. It would be blind to the evals most likely to hide a comparability
problem. Its demonstrated value is in one-shot audits:

- a dataset diff across a known change, which found the sciknoweval loss;
- a same-code double build, which found evals whose exam changes on every run.
