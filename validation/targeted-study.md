# Targeted validation study

**Date:** 2026-09-21 · **Package:** v0.1.0, re-run on v0.1.1 · `inspect-ai` 0.3.266 · Python 3.12.8
**Pre-registration:** [`scorer-manifest.yaml`](scorer-manifest.yaml), committed at `3d5c263` **before**
any probe was run. **Harness:** [`run_targeted_study.py`](run_targeted_study.py).
**Cell-level data:** [`targeted-study.csv`](targeted-study.csv), [`targeted-study.json`](targeted-study.json).

> ## Correction, 2026-09-22
>
> **This study originally claimed "1 genuine defect / 12 applicable cells". The correct count of
> defects attributable to `inspect_evals` is 0.**
>
> The one declared FAIL — `zerobench` flipping CORRECT → INCORRECT on `{ Paris }` — is real and
> reproduces. But `inspect_evals/zerobench` is a **port**, and the ZeroBench authors publish their
> scoring loop inline in their own README with the identical unstripped extraction. The port is
> faithful. A PR "fixing" it would be asking `inspect_evals` to diverge from the reference
> implementation, which is not a defect report.
>
> I checked the port's README prose and rejected a counter-argument from it (below, kept as written).
> I did not check the authors' **code**, which was published the whole time and settles it. The
> measured results are unaffected — `targeted-study.json` and `.csv` are unchanged, and the `FAIL` is
> still the right outcome. Only the attribution was wrong.
>
> Full evidence, plus the same check run against three other findings, in
> [`provenance-audit.md`](provenance-audit.md). Three of four inverted. The missing step is now part
> of the method: **fetch the reference implementation before calling a FAIL a defect.**

## Research question

An earlier blind sweep pointed these probes at 62 scorers with guessed input formats and no declared
exclusions. It produced 6 FAIL cells of which 1 held up as a real verdict change. This study tests the
opposite condition:

> When an evaluator reads a scorer's contract first and deliberately selects contract-preserving
> transformations, do these probes provide useful additional scrutiny of deterministic Inspect
> scorers and metrics?

The desired answer is not "the package finds bugs". It is whether *contract-aware* use is worth the
manual effort it costs.

## Selection methodology

12 scorers from `inspect_evals` and `inspect_ai` core, chosen for diversity of mechanism across five
categories. `prior_knowledge` was recorded per scorer **before** probing, so a defect in a scorer I
already knew about cannot be presented as new. Seven were UNEXAMINED.

Three cells were deliberate calibration:

- **`vqa_rad` and `aime_scorer`** — believed CLEAN, as false-positive controls.
- **core `match(numeric=True)`** — a defect I found **by hand** earlier (5-significant-figure
  normalisation grades 999999 equal to 1000000), included to test whether targeted probing re-finds
  it. A FAIL there would not have been a discovery.

**A category I could not fill.** "Code/format-sensitive" is near-empty inside V0.1. Every code scorer
in `inspect_evals` executes code in a sandbox — `apps`, `mbpp`, `humaneval`, `class_eval`, `usaco`,
`scicode`, `swe_bench`, `frontier_cs`, `compute_eval`, `kernelbench`, `livecodebench_pro`, `ds1000`,
`bigcodebench`. The one candidate whose docstring claims determinism with no LLM,
`cyberseceval_4.security_scorer`, needs `semgrep`, `sacrebleu` and `codeshield`, none installed.

## Scorers

| scorer | category | mechanism | prior knowledge | exercised |
|---|---|---|---|:--:|
| `zerobench_scorer` | text-extraction | strip+lower both, extract last `{...}`, compare | UNEXAMINED | ✓ |
| `best_elicitation_per_challenge` (threecb) | text-extraction | `target.strip() == completion.strip()` | light | ✓ |
| `vqa_rad_graded_scorer` | text-extraction | `AnswerPattern.LINE`, `.strip().lower()` both | believed clean | ✓ |
| `aime_scorer` | numeric | last line, unbox, `match_str(numeric=True)` | believed clean | ✓ |
| core `match(numeric=True)` | numeric | numeric comparison | **known defect** | ✓ |
| `mmiu_scorer` | structured | wraps core `choice()` | UNEXAMINED | ✓ |
| `tac_scorer` | structured | last `purchase_tickets` tool call; dict Score | UNEXAMINED | ✗ |
| `bfcl_scorer` | structured | AST / irrelevance match over tool calls | light | ✗ |
| `security_scorer` (cyberseceval_4) | code-format | static insecure-code detection | UNEXAMINED | ✗ |
| `make_me_pay_scorer` | custom | `Score(value=metadata['donation_amt'])` | UNEXAMINED | ✗ |
| `makemesay_scorer` | custom | outcome from a `Game` object in metadata | UNEXAMINED | ✗ |
| `ape_scorer` | custom | means over `metadata['turn_scores']`, emits NaN | UNEXAMINED | ✗ |

## Results

19 pre-registered (scorer, invariant) contracts expanded to **34 executed cells**, because several
transformations test one invariant. Plus **5 negative controls**, added after the frozen set and
explicitly identified as new cells.

| | declared (34) | negative controls (5) |
|---|---:|---:|
| PASS | 11 | 0 |
| FAIL | **1** | 4 *(correct)* |
| NOT_APPLICABLE | 19 | 0 |
| EXCLUDED | 3 | 0 |
| ERROR | 0 | 1 *(correct)* |

**Applicable cells** (PASS or FAIL) = 12 of 34. **Scorers exercised** = 6 of 12.

### Defect discovery rate

**0 defects attributable to `inspect_evals` / 12 applicable cells.** One declared cell FAILed and the
mechanism is real, but it is inherited from the benchmark's reference implementation — see the
correction above and [`provenance-audit.md`](provenance-audit.md).

**1 reproducible scorer-behaviour finding / 12 applicable cells = 8.3%** is the defensible version of
the original number. It is not a prevalence estimate either: the sample is purposive, small, and
includes two scorers selected *because* I believed them clean.

### Classification of every FAIL

| cell | classification |
|---|---|
| `zerobench` / `CUE_WHITESPACE` / `target_space_padded` | **real verdict change, inherited from the reference implementation** — not a port defect (was: "A — genuine scorer defect") |
| negative control ×4 (`zerobench`, `threecb`, `aime`, `core_match_numeric`) | correct behaviour: the answer genuinely changed |
| negative control, `vqa_rad` → `ERROR` | correct behaviour: see below |

No cell was classified C (invalid invariant), D (transformation problem), E (abstraction failure) or
F (inconclusive) — because those conditions surfaced as `NOT_APPLICABLE` rather than as FAILs, which
is the outcome routing working as designed.

**The `vqa_rad` negative control ERROR is worth its own note.** My control replaced `ANSWER: yes`
with `ANSWER: no`, which made case 0 identical to case 1. The framework's duplicate-case guard caught
it — `TRANSFORM_CONTRACT_VIOLATED: case_duplicated: produced 1 duplicate case(s) absent from the
input` — and attributed it to the transformation, not the scorer. That guard existed only against
synthetic tests until this study; here it caught a real accident of mine.

## The one declared FAIL

**`zerobench_scorer`** — `inspect_evals/zerobench/scorer.py:27`. Real and reproducible, but **inherited
from the reference implementation** and therefore not a defect in `inspect_evals`; see the correction at
the top and [`provenance-audit.md`](provenance-audit.md). The mechanism below is as originally measured.

| | |
|---|---|
| Mechanism | Strips and lowercases the whole completion and the target, extracts the last `{...}` group, then requires the extracted text to equal the target. |
| Original input | `"Working through it.\nThe answer is {Paris}"`, target `"Paris"` |
| Transformed input | `"Working through it.\nThe answer is { Paris }"` |
| Expected relationship | EQUAL — pre-registered rationale: *the scorer strips the completion, showing that surrounding whitespace is not meant to be significant; `{ Paris }` and `{Paris}` state the same answer* |
| Observed | `CORRECT → INCORRECT`; accuracy 0.5 → 0.0 |
| Root cause | The `.strip()` is applied to the **completion**, never to the **extracted group**. `re.findall(r"\{(.*?)\}", ...)` captures the interior verbatim, so `parsed_answer` is `' paris '` and the equality test fails. |

Minimal reduction, run directly against the scorer's logic:

```
'The answer is {Paris}'       -> CORRECT    parsed='paris'
'The answer is { Paris }'     -> INCORRECT  parsed=' paris '
'The answer is {Paris }'      -> INCORRECT  parsed='paris '     <- ONE trailing space
'  The answer is {Paris}  '   -> CORRECT                        <- OUTER whitespace is stripped
'The answer is {PARIS}'       -> CORRECT                        <- case IS handled
```

**Existing scorer tests:** `tests/zerobench/test_zerobench_scorer.py` has five —
`correct_word`, `correct_number`, `correct_sequence`, `incorrect_word`, `incorrect_number`.

**Why they did not catch it:** they exercise the happy path and the wrong-answer path with
tightly-delimited answers. None places whitespace inside the braces. The scorer's own normalisation
(strip the completion, lowercase both sides) makes whitespace *look* handled, and it is — everywhere
except the one string that actually gets compared.

**The counter-argument, recorded rather than dismissed:** `zerobench/README.md:81` says correctness is
determined by exact matching even for numerical answers, and someone could argue that licenses
whitespace sensitivity. I reject it, because the scorer itself strips and lowercases — it is not
performing exact matching on raw text, it is normalising and then matching, and the normalisation is
applied to the wrong string. But the reader should know the argument exists.

**Resolved 2026-09-22, and not in my favour.** I was arguing about the *port's* README. The ZeroBench
authors publish their scoring loop inline in *their* README, and it performs the same unstripped
extraction — so the port is faithful and the question of what the prose licenses is moot. The right
check was never "what does the documentation say", it was "what does the reference implementation do."
I weighed the wrong evidence while the decisive evidence sat one `curl` away, and only looked after
building a fix. See [`provenance-audit.md`](provenance-audit.md).

## A package defect the study found

Running against **v0.1.0**, `ape_scorer` returned `ERROR(NONREPEATABLE_BASELINE)`. The scorer is
perfectly repeatable; the package was wrong.

`nan != nan` propagates into containers, so two dicts holding equal-but-distinct NaN floats compare
unequal. `ape` returns a dict-valued `Score` with NaN fields **on purpose**, to exclude a sample from
aggregation rather than drag the mean toward zero — exactly the case v0.1.0 mishandled. A second path
was affected with no symptom yet: `compare_verdict`'s EQUAL branch used a bare `==`, so a dict-valued
verdict containing NaN would have been reported as changed when nothing changed — a false FAIL
waiting to happen.

Fixed in **v0.1.1** with one recursive comparison shared by both paths, and eight regression tests.
The affected cell was re-run; `ape` now reports `NOT_APPLICABLE`, correctly.

## Which transformations actually applied

| transformation | family | applied | not applicable |
|---|---|---:|---:|
| `target_space_padded` | target-anchored | 5 | 5 |
| `target_bolded` | target-anchored | 2 | 0 |
| `target_case_flip` | target-anchored | 2 | 1 |
| `cue_case_flip` | cue-anchored | 2 | 1 |
| `cue_space_removed` | cue-anchored | 1 | 9 |
| `answer_bolded` | cue-anchored | 0 | 2 |

**Target-anchored: 9 applied, 6 not. Cue-anchored: 3 applied, 12 not.** The target-anchored family,
added because the blind study showed cue-anchored probes reaching almost nothing, carried this study
too — and the one declared FAIL was found by `target_space_padded`, a transformation a cue-anchored
probe could not express.

## Why half the scorers could not be exercised

This is the most useful result, and it is sharper than "V0.1 limitations":

| scorer | why not exercised |
|---|---|
| `tac_scorer` | verdict comes from a **tool call in `messages`**, not from prose |
| `bfcl_scorer` | same — correct iff no tool call was made |
| `make_me_pay_scorer` | verdict is `metadata['donation_amt']`; the completion is never read |
| `makemesay_scorer` | verdict comes from a `Game` object in metadata |
| `ape_scorer` | verdict is a mean over `metadata['turn_scores']` |
| `security_scorer` | `CODE_FORMATTING` ships with **no transformation at all** |

Five of the six are unexercised for one reason: **the verdict does not depend on model text.** No
text-perturbing transformation can be a valid probe of a scorer that reads solver-computed state.
That is not a gap to close by adding `TaskState` fields to `Case` — supplying the metadata works
fine; there is simply nothing meaning-preserving to perturb.

So the scope statement is:

> These probes apply to scorers that **parse model output**. They do not apply to scorers that read
> state a solver computed, however that state is supplied.

The sixth is a genuine package gap: `CODE_FORMATTING` is advertised in the README's invariant table
and has no transformation, so it can only ever return `NOT_APPLICABLE`.

## Comparison with the 62-scorer blind study

| | blind | targeted |
|---|---|---|
| scorers | 62 | 12 |
| scorers exercised | 8 (13%) | 6 (**50%**) |
| FAIL cells | 6 | 1 declared (+4 negative controls, correct) |
| reproducible findings | 1 | 1 |
| of those, attributable to the port | unaudited (see below) | **0** |
| false positives among FAILs | **5 of 6** | **0 of 1** |
| effort | minutes, automated | ~20 min per scorer, manual |

Targeted use did **not** find more defects. It found the same number with no false positives instead
of five, and with a 4× better chance of reaching a scorer at all. Where the blind study's false
positives came from — asserting `MARKUP` on a scorer whose prompt forbids it — this study pre-emptively
declared 3 exclusions with written reasons, and that is precisely where those false positives went.

The comparison is qualitative. Different scorer sets, tiny samples, no statistical claim.

## Audit

Every number above is re-derived from [`targeted-study.json`](targeted-study.json) by
[`audit_study.py`](audit_study.py), not transcribed by hand — this project has twice published two
different totals for the same thing when counting in prose. The audit also asserts six post-v0.1.1
conditions, and runs in CI so the frozen result cannot drift:

```
1. no package-induced baseline error remains          (ape exercised, not ERROR)
2. the zerobench mechanism still reproduces           (FAIL, scorer+metric, 1/2 cases)
3. all three declared exclusions remain EXCLUDED
4. all 11 expected-robust cells remain PASS           (incl. both control scorers, every cell)
5. no ERROR or SETUP_FAILED among declared cells
6. the one control ERROR is attributed to the TRANSFORMATION, not the package

15 of 15 quoted counts match the data.
```

Condition 2 is a check that the *measurement* is stable, not that the finding is a port defect — the
2026-09-22 provenance audit reclassified it as inherited. The audit script cannot check provenance,
because provenance lives in another repository; that check is manual and recorded in
[`provenance-audit.md`](provenance-audit.md).

## Limitations

- 12 scorers, purposively selected. Nothing here estimates defect prevalence in Inspect.
- Two of the 12 were chosen *because* I believed them clean, which inflates the PASS count by design.
- One reproducible finding is a thin basis for any conclusion about discovery power — and after the
  provenance audit it supports **no** conclusion about finding defects in `inspect_evals`, because it
  was not one.
- Every scorer here is a port of someone else's benchmark, and this study did not check any of them
  against its reference implementation. That omission is what the 2026-09-22 correction fixes; the
  blind study's `docvqa` finding is still unaudited on the same axis.
- The in-scope/out-of-scope reasoning for unexercised scorers is from reading source, not from
  exhaustively attempting every possible `Case`.
- `cyberseceval_4` was never exercised, so the code/format category is untested rather than shown
  clean, and `CODE_FORMATTING` remains entirely unexercised by anything.
- I wrote both the probes and the study. A second person choosing the invariants would be better
  evidence, particularly for the one FAIL, where the judgement that whitespace inside a delimiter is
  insignificant is mine.

## Conclusion

**Moderate validation, downgraded from "moderate-to-strong" by the 2026-09-22 correction.**
Contract-aware use is materially better than blind use on the two things that decide whether anyone
would trust the tool: it reached 50% of selected scorers versus 13%, and produced no false positives
versus five in six. Both of those still hold — they are properties of the probing method, not of the
attribution. It also found a real defect in the package itself, which is the outcome I would least have
predicted and possibly the most valuable.

What does **not** hold is the headline it was written around. The one previously unknown finding in an
UNEXAMINED scorer is real and reproducible in five lines, and the eval's own five scorer tests do not
cover it — but it is a faithful reproduction of the benchmark authors' scoring code, so it is not a
defect in `inspect_evals`. On the question this study was built to answer, the honest count is zero.

Against that: the methodology costs roughly twenty minutes of reading per scorer, it only applies to
scorers that parse model output — which excluded half of a set chosen for diversity — and, as the
correction shows, it needs a further provenance check per finding before any finding can be attributed.
The honest summary is that this is useful scrutiny for a specific and identifiable class of scorer, not
a general-purpose check, and that its output is a question rather than a verdict.

### The claim worth making

> **The value of these probes comes from knowing what the scorer is supposed to preserve — not from
> applying a larger generic battery of transformations.**

That is the methodological lesson, and it is supported in both directions by the two studies rather
than by one of them. Blind application of a generic battery reached 13% of scorers and produced five
false positives in six FAILs. The same battery, aimed by someone who had read the contract first,
reached 50% and produced none. The transformations did not change between the two studies. The only
thing that changed was whether the invariant was chosen by a human who knew what the scorer promised.

Three corollaries follow, and all three cut against building more:

- A larger transformation library would not have helped. Of the 12 scorers, six were unexercisable and
  five of those because the verdict does not read model text at all — a gap no transformation closes.
- The one declared FAIL was found by a transformation whose *rationale* was written before it ran.
  Had the same FAIL arrived from an undeclared generic sweep, it would have been indistinguishable
  from the four exclusions that a contract-aware reading correctly ruled out in advance.
- **Added 2026-09-22.** Declaring the invariant is necessary but not sufficient. A declared invariant on
  a *ported* scorer is really a claim about the reference implementation, and nothing in the probe tells
  you which of the two you are testing. That check is reading, not code — so the gap this study
  exposes is in the workflow, not in the package.

**What follows for the package, and what does not.** The workflow worth considering later is narrow:
read the scorer, decide what its prompt permits, write two cases, declare the invariant, run — then,
before attributing any FAIL, fetch the reference implementation and check it does not do the same thing.
The two things that would most improve the package are a transformation for `CODE_FORMATTING` or its
removal from the advertised set, and a fast way to tell whether a scorer reads model text at all — that
single question predicted exercisability in 11 of 12 cases. Neither justifies expanding the abstraction,
and neither should begin before someone other than the author has used the workflow on their own scorer.
