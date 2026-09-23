# inspect-audit diff — result against the pre-registration (`PREREG.md`, commit 0bebad0)

Upstream `inspect_evals` worktrees built from the named commits; `inspect_ai` 0.3.268 for replays,
unit tests also on 0.3.266. No model calls anywhere except the 60 stored luna AIME transcripts
re-used from earlier runs, and those were re-scored with `mockllm` as the (unused) model.

## Verdict: PASS on dataset diff and on "verdicts unchanged, metrics changed".
## "Verdicts changed" is NOT validated on history (R3 uninformative, as pre-registered risk).

| | case | pre-registered expectation | observed | |
|---|---|---|---|---|
| R1 | worldsense, #940 | 46,872 removed, 0 added; FALSE/IMPOSSIBLE/"2" -> 0 | exactly that; plus 40,176 id changes | PASS |
| R2 | sciknoweval, #940 | ~3,810 removed; material_toxicity >= 90% loss; ids as id-changed | 3,810 removed; material_toxicity 615 -> 4 (-99.3%); 66,386 id changes, 0 churn | PASS |
| R3 | aime_scorer, #2025 | verdict transitions on 60 transcripts, or UNINFORMATIVE | **0 transitions** in 60 — luna always ends on the answer | UNINFORMATIVE |
| R4 | worldsense metric patch (self-authored) | verdicts unchanged, metrics changed | exactly: ws_accuracy/ws_bias 0.0 -> 1.0, accuracy and 10/10 verdicts held | PASS |
| N1 | worldsense across a commit that does not touch it | empty | empty | PASS |
| N2-N5 | self / permuted / metadata-only / id-only | empty / empty / metadata-only / id-only | as stated (unit tests) | PASS |
| N6 | log vs itself; log vs re-scored with same scorer | empty | empty (unit tests; and 6/6 real AIME logs re-scored post-fix reproduce the stored log exactly) | PASS |
| N7 | model-graded scorer | refusal with reason | refused: "scoring called a model ..." (unit test, real model_graded_qa with a mock grader) | PASS |

"Verdicts changed" IS exercised by a unit test (a real `inspect eval` re-scored with a different
scorer logic: `'I' -> 'C'` on sample 1), but that is synthetic. No historical case has shown it yet.

## Defects in the tool found by the replay itself (fixed, with regression tests)

1. **Snapshot load split records on U+2028.** `str.splitlines()` splits on Unicode line separators
   and the file was written with `ensure_ascii=False`; SciKnowEval text contains them. Failed LOUDLY
   (exit 2), not silently. Fixed: ASCII-escaped JSON, split on `\n` only.
2. **408 phantom "metadata changed" in R2.** Removing one of two identical duplicates made the
   compared lists differ in length, so an untouched sample read as changed. Would have been reported
   as a finding. Found by asking what the 408 were and reading them: the differing metadata keys were
   the empty set. Fixed by counting over matched copies (multiset intersection), for ids as well.

## What this does not establish

- Anything about demand. It shows the tool would have surfaced two real defects at review time on one
  PR (#940), from one bug family.
- That verdict-transition diffs work on a real historical scorer change (R3 was uninformative).
- Coverage of evals whose datasets are gated, need extras, or cannot be built at an old commit.

## Reproduce

Dataset: build `inspect-audit snapshot inspect_evals/<task> -o X.jsonl` inside each worktree with
`PYTHONPATH=<worktree>/src` (sciknoweval must run with the worktree as cwd — it reads a file by
relative path), then `inspect-audit diff dataset before.jsonl after.jsonl`.
Scores: `rescore_aime.py`, `ws_mock_log.py`, `ws_rescore.py` in this directory. Outputs in `outputs/`.
