# Changelog

## Unreleased

- **New: `inspect-audit diff`** — observed differences between two states of an evaluation, no model
  calls. `snapshot` a task's dataset; `diff dataset` matches samples by content hash (not id) and
  reports removed / added / id-changed / metadata-changed with per-group and per-target deltas;
  `diff scores` compares two logs of the same transcripts and refuses when scoring called a model.
  Validated against pre-registered replays of `inspect_evals` #940 and #2025
  (`validation/diff/RESULT.md`).
- README: install instruction corrected (the package is not on PyPI), and the probe-layer headline
  corrected — two of its three original findings were inherited from reference implementations.

## 0.1.0 — 2026-09-21

First release. Metamorphic invariance probes for Inspect AI scoring pipelines: given a contract the
caller declares and a transformation the caller has licensed, does the pipeline satisfy the contract?

- **Probes the scorer AND the metrics**, not the scorer alone. The defect that motivated this is
  invisible at the scorer layer: per-case verdicts identical, weighted metric 1.0 → 0.0.
- **Explicit invariant contracts.** `invariants` is required and `exclusions` are recorded; the
  contract is serialised and hashed, so silencing a FAIL by excluding an invariant is visible.
- **Five outcomes kept distinct** — `PASS`, `FAIL`, `NOT_APPLICABLE`, `ERROR`, `EXCLUDED`. No
  requested observation can silently become a PASS: a metric that is not a scalar makes the outcome
  `ERROR`, and a contract that executes nothing fails the assertion.
- **Transformation contracts, verified at runtime.** Each transformation declares what it `tests`,
  what it `mutates` and what it `holds_fixed`; the framework diffs against that declaration and
  attributes any violation to the transformation, never to the scorer.
- **Repeatability checks.** The baseline is observed twice and the runs must agree. This is a guard
  against unstable observations, not a proof of determinism.
- **Metric-level divergence detection.** When the scorer layer is clean and some but not all metrics
  move, the report says so — the only thing separating a silent collapse from a legitimate value.
- **Five invariants**: `CUE_WHITESPACE`, `CUE_CASE`, `MARKUP`, `CODE_FORMATTING`,
  `WRONG_STAYS_INCORRECT`. Two families of transformation, cue-anchored and target-anchored.
- **Validated against real Inspect evaluations.** Three defects found in `inspect_evals`
  (`worldsense`, `novelty_bench`, `tau2`), a 12-cell scorecard with 3/3 positives and 0/9 false
  FAILs, and a measured reach figure across 62 real scorers — reported with its limits, including
  that pointed blindly the tool is close to useless.

Named `inspect-scorer-probes` because what it probes is a scorer and the metrics computed from it,
not an eval. An earlier working name implied a relationship with the `inspect_evals` collection that
does not exist.

Known limitations are documented in the README rather than here. In particular: offline and
deterministic is a precondition the package does not enforce; model-graded scorers are out of scope
and are not detected; and `Case` supports only `completion`, `target`, `metadata`, `messages` and
`input`.

## 0.1.1 — 2026-09-21

One correctness fix, found by running the targeted validation study against 0.1.0.

- **NaN inside a container broke repeatability and verdict comparison.** `nan != nan` propagates
  into dicts, lists and tuples, so two equal-but-distinct NaN values compared unequal. A scorer that
  deliberately emits NaN inside a dict-valued `Score` — `inspect_evals`' `ape` does, to exclude a
  sample from aggregation rather than drag the mean to zero — was reported
  `ERROR(NONREPEATABLE_BASELINE)`, and its verdicts would have been reported as changed when nothing
  changed. Comparison is now recursively NaN-aware, shared between the repeatability check and the
  verdict comparator so the two cannot drift apart. Eight regression tests.

## 0.1.2 — 2026-09-21

Documentation honesty, no behaviour change.

- **`CODE_FORMATTING` was advertised in the README's invariant table and ships no transformation**, so
  it could only ever return `NOT_APPLICABLE`. That was an overclaim in a package whose entire pitch is
  not overclaiming. The table now separates the three invariants that work out of the box from the two
  that are declared but require a caller-supplied transformation, with the reason for each. Both
  invariant descriptions say so in code as well as in the README.
- `WITHOUT_BUILTIN_TRANSFORMATION` is exported and pinned by a test, so a future invariant cannot
  silently become a third advertised-but-dead entry.
