# inspect-audit diff — pre-registration (written BEFORE any diff code, 2026-09-23)

## Question
Can `inspect-audit diff` surface known evaluation-state changes that affect dataset composition or
scoring comparability, using only observable artifacts of two states — no model, no judge, no
inferred semantics?

## Design commitments (fixed now)
- The primitive is TWO STATES, not git refs. A dataset state is a snapshot file; git-ref building is
  a convenience that produces snapshots.
- SAMPLE IDENTITY IS A CONTENT HASH (input text, choices, target), not the sample id. PR #940 changed
  ids as well as dropping rows, and pre-#940 worldsense had 87,048 rows under 40,176 ids, so id
  matching is both misleading and undefined. States are compared as MULTISETS of content hashes.
- Dataset diff categories: removed, added, unchanged, id-changed (same content, different id),
  metadata-changed (same content, different metadata). Every count lists example sample ids.
- Decomposition by metadata group (every scalar metadata key with <= 50 distinct values) and by
  target is REQUIRED output, not optional: sciknoweval's #940 loss is invisible in the totals.
- Score diff compares two logs over the same transcripts (matched by id+epoch, content-checked;
  refuses on mismatch). Output: per-scorer verdict transitions with sample ids, metric deltas, and
  the split {verdict changed / unchanged} x {metric changed / unchanged}.
- Score diff REFUSES attribution when the scoring phase of either log contains model calls
  (observable in sample events), stating why. It never guesses.
- Nothing is labelled a bug, defect or error. Output reports observed differences only.

## Historical replays (primary success criterion)
R1 worldsense, PR #940 (93936ae15^ vs 93936ae15): must report 46,872 rows removed, 0 added, and the
   targets FALSE, IMPOSSIBLE and "2" going to zero. (Independent manifest, measured earlier today:
   87,048 -> 40,176; 7 targets -> 4.)
R2 sciknoweval, PR #940: must report ~3,810 rows removed overall AND, in the per-group breakdown,
   material_toxicity_prediction losing >= 90% of its rows. Id changes must be reported as
   id-changed, not as add/remove churn.
R3 aime_scorer, PR #2025 (5c8626ed2^ vs 5c8626ed2), deterministic scorer: re-score 60 stored luna
   transcripts (aime2024 x30, aime2025 x30; post-fix scores stored) with the pre-fix scorer; report
   verdict transitions with sample ids. IF ZERO TRANSITIONS: R3 is UNINFORMATIVE, not a pass, and the
   "verdict changed" class is unvalidated on history.
R4 (self-authored, labelled as such) worldsense metric patch, branch fix/worldsense-weighted-metric-case:
   on a mockllm title-cased log, must report "verdict unchanged, metric changed".

## Controls (must all come out as stated)
N1 upstream: worldsense at e3402e36c vs its parent (eval code untouched) -> empty dataset diff.
N2 snapshot vs itself -> empty.       N3 row order permuted -> empty.
N4 metadata-only edit -> metadata-changed only, 0 added/removed.
N5 id-only edit -> id-changed only, 0 added/removed.
N6 log vs itself (score diff) -> empty.
N7 a model-graded scorer log -> refusal with reason, no transitions reported.

## Verdict rule
MVP PASSES only if R1 and R2 match, at least one of R3/R4 demonstrates each score-diff class it
claims, and N1-N7 all behave as stated. Anything else is reported as a failure with the output.
