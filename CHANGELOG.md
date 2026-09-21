# Changelog

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

Known limitations are documented in the README rather than here. In particular: offline and
deterministic is a precondition the package does not enforce; model-graded scorers are out of scope
and are not detected; and `Case` supports only `completion`, `target`, `metadata`, `messages` and
`input`.
