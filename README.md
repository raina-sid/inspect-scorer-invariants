# inspect-scorer-probes

Evidence for auditing [Inspect AI](https://inspect.aisi.org.uk) evaluations when they change.

**Observation is automatic; interpretation is yours.** Nothing here decides whether an evaluation is
correct. It reports what changed between two states of an evaluation, where, and which samples to
read — and it tests explicit contracts you declare. It never infers one.

Two layers:

| | question it answers | needs |
|---|---|---|
| **`inspect-audit diff`** | What changed between these two states of an eval? | two dataset snapshots, or two logs of the same transcripts |
| **metamorphic probes** | Does my scorer honour the contract **I declared**? | a contract and cases you write |

Not on PyPI. Install from git:

```bash
pip install "git+https://github.com/raina-sid/inspect-scorer-probes"
```

---

## `inspect-audit diff`

### Why a diff

Every scorer or dataset PR to an eval raises the same question — *is this still comparable with
results produced before it?* — and `inspect_evals`' own `TASK_VERSIONING.md` asks authors to answer
it. Today that is answered by reading code. Inspect records everything needed to answer it from
evidence, but nothing compares two states.

What we measured before building this: single-run heuristics over logs flagged 7 things on 20 fresh
evals and none was real; recomputing a run's metrics from its own stored scores reproduced all 232
logs we tried, by construction. The findings that were real all came from **comparing two states**.

### Use

```bash
# dataset: build the task's dataset as an eval would (no model calls), in each state
inspect-audit snapshot inspect_evals/sciknoweval -o before.jsonl     # at the old code
inspect-audit snapshot inspect_evals/sciknoweval -o after.jsonl      # at the new code
inspect-audit diff dataset before.jsonl after.jsonl [--json]

# scores: re-score the SAME transcripts with changed scorer/metric code, then diff
inspect score base.eval ...                                          # Inspect's own re-scoring
inspect-audit diff scores base.eval rescored.eval [--json]
```

Exit status `0` no differences, `1` differences observed, `2` refused or error. A difference is not a
failure; the code exists so CI can notice.

### What it looks like

Replaying `inspect_evals` PR #940 on `sciknoweval` (abridged):

```
samples (matched by content: input + choices + target)
  before               70,196
  after                66,386
  removed               3,810
  added                     0
  id changed           66,386   (same content, different sample id)
  metadata changed          0

by group (largest relative loss first)
  task   material_toxicity_prediction        615 ->        4  (-99.3%)
  type   mcq-2-choices                       746 ->        9  (-98.8%)
  task   proteotoxicity_prediction           510 ->      172  (-66.3%)
  task   molecular_property_prediction     2,365 ->      822  (-65.2%)
```

The total says 5%. The group breakdown says one task is now scored on 4 questions. Group
decomposition is part of the result for that reason.

### What it observes, and how

- **Samples are matched by content** (input text, choices, target), not by id. Ids change without
  content changing, and can repeat; matching on them reports churn that is not there. Id and
  metadata changes on unchanged content are reported as their own categories.
- **States are multisets**: row order never matters, duplicates are counted, not collapsed.
- **Every count names example sample ids** to go and read.
- **`diff scores` refuses rather than guesses** when either log's scoring phase called a model (a
  `ModelEvent` inside Inspect's `scorers` span): a judge re-roll alone changes scores, so a difference
  cannot be attributed to scorer code. It also refuses when the two logs are not the same transcripts,
  and on header-only logs.
- It separates **verdicts changed** from **verdicts unchanged, metrics changed** — the second is an
  aggregation change that no per-sample check can see.

### What it cannot observe

- Whether a difference is intended, harmful or fine. That is yours to decide.
- Model-graded scoring differences (refused by design, above).
- Datasets that are gated, need extras or a sandbox to build, or that no longer build at an old
  commit. Snapshots are the primitive for this reason: build each state wherever it builds.
- Anything outside the dataset and scores: solver changes, tool behaviour, environment drift.
- Task lookup uses two private Inspect calls (there is no public API); they are isolated in one place
  and fail with an explicit error if Inspect changes them.

### Validation

Pre-registered before any code was written ([`validation/diff/PREREG.md`](validation/diff/PREREG.md)),
result in [`validation/diff/RESULT.md`](validation/diff/RESULT.md):

| replay | observed | |
|---|---|---|
| worldsense, PR #940 | 46,872 removed; targets `FALSE`, `IMPOSSIBLE`, `2` -> 0 | pass |
| sciknoweval, PR #940 | 3,810 removed; `material_toxicity_prediction` 615 -> 4 | pass |
| aime_scorer, PR #2025 | 0 verdict transitions in 60 real transcripts | uninformative |
| worldsense metric patch (self-authored) | verdicts unchanged, metrics changed | pass |
| 7 controls (self, reordered, id-only, metadata-only, model-graded, ...) | as stated | pass |

**"Verdicts changed" is exercised only synthetically so far** — no historical scorer change we
replayed produced a transition. The replay also found two bugs in the tool itself, both fixed with
regression tests. Nothing here measures demand: it shows the tool would have surfaced two real
defects at review time, on one PR, from one bug family.

---

# Explicit contracts: metamorphic scorer probes

Existing scorer tests can establish that a scorer behaves correctly on its fixtures. They do not
establish that the **measurement** stays invariant under transformations the task contract treats as
semantically irrelevant.

In a pre-registered run across 18 Inspect evals, a frozen set of such transformations exposed three
failures, spanning both scorer-level and metric-level behaviour. A later provenance audit found two
of the three were faithful reproductions of the benchmarks' own reference implementations, not
defects of the Inspect ports (see [the scorecard](#two-of-the-three-positives-are-not-inspect_evals-bugs)).

This layer answers exactly one question:

> Given a contract **C** and a transformation **T**, does pipeline **P** satisfy **C**?

It does **not** decide whether C is semantically right for the task. That judgment stays with you, is
recorded in the report, and is hashed.

## Install

Installed with the package above.

### Supported versions

Tested for 0.1.0 on **Python 3.11, 3.12 and 3.13** with **`inspect-ai` 0.3.266**, by clean install
into a fresh virtualenv on each. The dependency floor is `inspect-ai>=0.3.266` — that is the version
tested, not a known minimum; older releases are untested. No broader compatibility is claimed.

The package itself makes no provider call, no network request and no sandbox call.

### Precondition: your scorer must be offline and deterministic

V0.1 is designed for offline, deterministic scorers. **The package does not enforce the absence of
provider or network calls.** Repeatability checks provide a limited guard against unstable
observations; they do not prove determinism.

Concretely: it does not sandbox your scorer, intercept sockets, or inspect what it calls. Hand it a
model-graded scorer and it may quietly produce a result, and that result will be meaningless. Meeting
the precondition is your responsibility.

### Scope: what a `Case` can represent

V0.1 supports scorers whose relevant `TaskState` inputs can be expressed as a `Case`:
`completion`, `target`, `metadata`, `messages`, `input`. A scorer that reads anything else — the store,
`output.choices`, tool calls, a sandbox — is outside what a `Case` can represent and therefore
outside V0.1. This is not a claim to cover arbitrary Inspect scorers.

## Use

```python
from inspect_ai.scorer import accuracy
from inspect_scorer_probes import CUE_CASE, Case, Contract, assert_invariants, probe

report = probe(
    scorer=my_scorer(),
    metrics={"accuracy": accuracy(), "weighted_accuracy": my_weighted_accuracy()},
    cases=[Case(completion="TRUE", target="TRUE"), Case(completion="FALSE", target="FALSE")],
    contract=Contract(invariants=[CUE_CASE]),
)
print(report.render())
assert_invariants(report)
```

A complete, runnable version — a scorer that is fine and a metric that is not — is
[`examples/quickstart.py`](examples/quickstart.py). It uses only the public API and runs offline:

```bash
python examples/quickstart.py
```

`probe()` is a synchronous convenience wrapper and cannot run inside an active event loop. From an
async test, or from inside an Inspect solver or scorer, use the async entry points — the sync
wrappers raise a message telling you so:

```python
report = await probe_async(...)      # and observe_async(...) at the lower level
```

`invariants` is required. A probe with no declared contract would have to assume every invariant
holds — which manufactures false positives on any task whose prompt rules one out — or assert nothing
at all.

### The one exclusion you almost certainly need

**If your prompt mandates an output format, exclude `MARKUP`.** Phrases to look for in your own
prompt: *"the entire content of your response"*, *"no other text"*, *"only respond with"*,
*"Return EXACTLY"*. In a blind sweep of real evals this single omission caused **4 of the 5 false
positives** — it is the modal user error by a wide margin.

Two related cases worth recognising, because they look like defects and are not:

- a scorer whose **purpose** is to check formatting (`personality` scores format compliance), where
  markup-sensitivity is the measurement, not a bug
- a scorer that **correctly tags** malformed input as unscored rather than mislabelling it
  (`stereoset` sets `unscored_reason='invalid_response_format'`). This probe compares `Score.value`
  and does not read `unscored_reason`, so it still reports a change. That is a limitation here, not
  a defect there.

## What a finding looks like

```
contract 7dd5897ee730
  invariants: CUE_CASE
  exclusions: MARKUP

  CUE_CASE  cue_case_flip  FAIL [METRIC]  4/4 transformed
  MARKUP    -              EXCLUDED

  1 executed | PASS 0 | FAIL 1 | ERROR 0 | NOT_APPLICABLE 0 | EXCLUDED 1

  --- CUE_CASE / cue_case_flip  FAIL [METRIC]
      Metrics:
        accuracy: 1.0 -> 1.0  ok
        ws_accuracy: 1.0 -> 0.0  [value_moved]  FAIL
      DIVERGENT_METRICS: verdicts unchanged; 1 of 2 metrics moved
```

That last line is the point. The per-sample verdicts are byte-identical and `accuracy` is unmoved, so
nothing at the scorer level looks wrong — while the reported weighted accuracy has gone to zero.
`DIVERGENT_METRICS` is what separates that from a legitimate score of zero.

This is a real defect, found this way. `worldsense`'s metric weight table is keyed uppercase-only
while its scorer is built `ignore_case=True`, so `"True"` is accepted by the scorer and then cannot be
keyed by the metric. Its own tests use uppercase answer literals throughout.

**A FAIL is not yet a finding, and the missing step is not in this tool.** If the scorer you are probing
is a **port** of a published benchmark — every `inspect_evals` scorer is — then the invariant you declared
is really a claim about the *reference implementation*, and a FAIL has two causes the probe cannot
distinguish: the port diverged, or the port faithfully reproduces a defective reference. Fetch the
reference and check before you attribute anything. Three of the four findings this package was built on
inverted on that check ([`validation/provenance-audit.md`](validation/provenance-audit.md)); `worldsense`
above is one that survived it, and it survived for a deeper reason than the case mismatch — the port keys
the metric weight off the model's answer where upstream keys it off the gold answer.

## The five invariants

**Three ship transformations and work out of the box:**

| invariant | asserts the observation does not depend on | transformations |
|---|---|---|
| `CUE_WHITESPACE` | whitespace around the answer cue | `cue_space_removed`, `target_space_padded` |
| `CUE_CASE` | case of the cue or the answer token | `cue_case_flip`, `target_case_flip` |
| `MARKUP` | markdown emphasis around the cue or the answer | `answer_bolded`, `target_bolded` |

**Two are declared but ship NO transformation.** You must supply your own, or they can only ever
return `NOT_APPLICABLE`:

| invariant | asserts | why nothing ships |
|---|---|---|
| `WRONG_STAYS_INCORRECT` | *(a relation, not equality)* a wrong answer stays wrong when replaced by a differently-wrong answer of the same shape | "a differently-wrong answer of the same surface shape" is domain knowledge; a generic guess would be the library smuggling an assumption into your test |
| `CODE_FORMATTING` | reindentation, blank lines, hoisted imports, fence-tag case | every code scorer in `inspect_evals` executes code in a sandbox, outside V0.1 scope, so there was no real scorer to validate a shipped rewrite against |

Transformations come in two families. **Cue-anchored** ones look for a known answer cue
(`ANSWER:`, `VERDICT:`) — precise when the convention matches, useless when it does not.
**Target-anchored** ones locate the target's own occurrence in the completion and perturb that, which
works whatever cue the scorer uses. The second family exists because of the measurement above: before
it, only 2 of the 8 observable scorers had any transformation apply; after it, all 8 did.

`scorecard/fixtures.py` has a worked example of supplying your own transformation.

Two further transformation families were in the pre-registered set and are **not** shipped:
`NUMERIC_EQUIVALENT` and `LEGITIMATE_DISTRACTOR` found nothing across all 18 evals. Shipping them
would claim coverage measured at zero.

## Five outcomes, and none of them collapses into PASS

| outcome | meaning |
|---|---|
| `PASS` | contract applicable, relation holds |
| `FAIL` | contract applicable, relation violated |
| `NOT_APPLICABLE` | the transformation cannot meaningfully apply here |
| `ERROR` | an observation or computation failed |
| `EXCLUDED` | you declared the task contract rules this invariant out |

The rule the routing exists to enforce: **no requested observation may silently disappear into
PASS.** `PASS` means the requested relation was actually tested and held — not merely that nothing
contradicted it.

That has a consequence worth knowing before you see it. A metric whose value is not a scalar — a
dict, a nested aggregate — **cannot be compared**, so a probe that requested it reports `ERROR`
rather than `PASS`, with an `UNCOMPARED_METRICS` detail naming the metric. Pass only comparable
metrics if you need a `PASS`. A real violation still reports `FAIL`, and still discloses that a
metric went uncompared.

`assert_invariants` raises on `FAIL`, and **also on `ERROR` by default**. An ERROR is not evidence of
a defect, but it is not evidence of correctness either, and a CI job that exits 0 on PASS + ERROR has
quietly converted "could not observe" into "fine". For exploratory use, `fail_on_error=False` warns
instead. Under either setting an ERROR is never represented as a PASS.

`EXCLUDED` and `NOT_APPLICABLE` never fail. Zero executed probes fails under both settings, because a
contract that observes nothing would otherwise stay green forever.

## Reproduction scaffolds

Every `FAIL` carries a `ReproductionScaffold`: both case lists, the verdicts, the metric values and
which case indices changed. It is called a **scaffold** because it is not necessarily a runnable
script — arbitrary scorer source cannot be reconstructed, so executable code is emitted only when you
pass `scorer_source="my_scorer()"`. `scaffold.is_runnable` tells you which you have, and
`scaffold.code` is `None` otherwise.

The whole case list is carried, not just the first changed case, because a metric-layer finding
cannot be reproduced from one case — an aggregate only moves once every case has been scored.

## Transformations declare their own contract, and the framework checks it

```python
Transform(
    name="cue_case_flip",
    tests={CUE_CASE},                 # which invariant this is valid evidence for
    mutates={"completion"},           # what it is licensed to change
    holds_fixed={"target", "metadata", "messages", "case_count"},
    apply=...,
)
```

After applying, the framework diffs the cases against that declaration. Any change outside `mutates`,
any added, dropped or duplicated case, and the result is `ERROR(TRANSFORM_CONTRACT_VIOLATED)` —
**attributed to the transformation, never to the scorer.** A scorer must not be reported as failing
because the thing probing it was wrong.

A transformation that changes nothing is `NOT_APPLICABLE`, not `PASS`.

**What that verification does and does not establish.** It checks *structural* compliance only:
which `Case` fields changed, and that the case count is preserved. It does **not** establish
*semantic* preservation — that flipping case, or wrapping an answer in asterisks, leaves the meaning
intact. That claim lives in the invariant **you** declared, which is why the contract is recorded and
hashed rather than inferred. A transformation can be perfectly compliant structurally and still be
semantically wrong, in which case the resulting `FAIL` is your error, not the scorer's.

## Repeatability, not determinism

The baseline is observed twice (`repeatability_runs=2`) and the runs must agree, or the whole probe
returns `ERROR(NONREPEATABLE_BASELINE)`. This establishes repeatability across the configured runs —
**not** determinism, and **not** that the scorer is offline. A judge at temperature 0, a cached
response, or any dependence that is stable within one session passes it. It is a weak safety net over
the precondition above, not a substitute for it.

## The scorecard

`python -m scorecard.summary` runs every validation cell and prints this:

```
  positive defect (3 cells)
    ok worldsense       CUE_CASE               FAIL      expected FAIL
    ok novelty_bench    MARKUP                 FAIL      expected FAIL
    ok tau2             WRONG_STAYS_INCORRECT  FAIL      expected FAIL

  contract exclusion (3 cells)
    ok frontierscience  MARKUP                 EXCLUDED  expected EXCLUDED
    ok core_choice      MARKUP                 EXCLUDED  expected EXCLUDED
    ok scbench          MARKUP                 EXCLUDED  expected EXCLUDED

  genuinely robust (6 cells)
    ok agieval          CUE_WHITESPACE         PASS      expected PASS
    ok frontierscience  CUE_WHITESPACE         PASS      expected PASS
    ok novelty_bench    CUE_CASE               PASS      expected PASS
    ok scbench          WRONG_STAYS_INCORRECT  PASS      expected PASS
    ok core_choice      CUE_WHITESPACE         PASS      expected PASS
    ok core_choice      CUE_CASE               PASS      expected PASS

  3/3 positive fixtures FAILed as expected
  0/9 negative fixtures produced a false FAIL
  12 cells total
```

**This is a validation fixture set, not an estimate of detector accuracy.** Twelve hand-picked cells
cannot measure how often the tool is right in general, and the three positives were *found by these
probes*, so detecting them is circular by construction. What the scorecard establishes is narrower and
still worth having: the mechanisms still reproduce, and the tool does not flag the negatives.

The negative arms are the ones that matter. The **exclusion** cells are real, reproducible verdict
changes that are *not* defects — `frontierscience` loses 8 points to `VERDICT: **8**`, but its prompt
says "no other text" and its own test suite asserts the strictness. Each exclusion cell is paired with
a test showing the change *is* real, so the exclusion is doing work rather than hiding an absence. The
**robust** cells show the tool does not condemn a scorer that is fine; the sharpest is `novelty_bench`,
which fails `MARKUP` and passes `CUE_CASE` — the same fixture, because its partition function
normalises case and whitespace and only misses markup.

Fixtures are vendored minimal reductions with provenance recorded in `scorecard/fixtures.py`, not calls
into `inspect_evals`. If these mechanisms are ever fixed, a scorecard calling the real scorers would turn
red — doing the right thing would destroy the evidence.

### Two of the three positives are not `inspect_evals` bugs

Every eval in `inspect_evals` is a **port** of someone else's benchmark, and for a port the contract is
fidelity to the reference implementation. A probe cannot tell a port divergence from a faithful
reproduction of a defective reference — but they need completely different audiences. Audited
2026-09-22, and it inverted three of four findings:

| fixture | reference implementation | who should hear about it |
|---|---|---|
| `worldsense` | **diverges** — the port keys the metric weight off the model's answer where upstream keys it off the gold answer, and drops the `resp_map` that makes the retained weights coherent | `inspect_evals` |
| `novelty_bench` | **identical**, verbatim four lines | the NoveltyBench authors |
| `tau2` | **identical**, and upstream carries its authors' own `# TODO: This could be improved!` on that line | the tau2-bench authors |

So a PR "fixing" `novelty_bench` or `tau2` would be asking `inspect_evals` to diverge from the
benchmark it is reproducing, which is a PR they should reject. Full evidence and the reproduction
commands are in [`validation/provenance-audit.md`](validation/provenance-audit.md).

**The step this adds to the workflow, and it is not optional: before attributing a FAIL to a scorer,
fetch the reference implementation and check whether it does the same thing.** It costs one `curl`. I
ran it after building a fix rather than before, which is how a wrong claim reached a published study.

## Reach: measured against 62 real scorers, and it is limited

Pointed **blindly** at every bespoke, offline-constructible scorer in `inspect_evals` — 62 of them —
with six guessed completion formats and no declared exclusions:

| | |
|---|---|
| outside what a `Case` can represent | **20** |
| in scope, but the guessed format was wrong | **30** |
| observed, and every probe exercised | **8** |
| FAIL cells produced | 6 |
| **a real verdict change rather than a false positive** | **1** |

The 20 break down as: needs a sandbox (10), reads the store (4), reads `state.input` (3 — which is
why `Case.input` now exists), reads `output.choices` (2), other `TaskState` (1).

**Two honest readings of that.**

Blind, it is close to useless: 1 true finding in 6 FAILs, and 30 of 62 scorers unreachable simply
because a generic guess at their input format is not good enough. **The package cannot be pointed; it
has to be aimed.** Someone probing their *own* scorer knows its format and its metadata keys, and
knows what their prompt permits — that is the difference between the 17% above and the three reproducible
findings this package was built on. (One of which survived the provenance check above; two did not.)

The one true finding is instructive: `docvqa` captures its answer with `match.groups()[0]` and **no
`.strip()`** (`docvqa.py:136`), while `vqa_rad` does `match.groups()[0].strip().lower()` in the same
repo. The captured text feeds an ANLS score with a hard `threshold = 0.5` cliff (`docvqa.py:92-98`), so a
single trailing space costs a 3-character answer 0.75 instead of 1.0, and for a 1-character answer the
normalised distance reaches 0.5 exactly and the score collapses to **0.0**. A cue-anchored transformation
missed it; a target-anchored one found it.

**Unaudited for provenance**, and the two things I first assumed about it were both wrong: the scorer is
not exact-match (it implements ANLS itself, `docvqa.py:72-100`), and the effect is a graded score
reduction rather than a corrupted comparison except at very short answers. Whether the reference
implementation normalises before scoring is the open question, and I have not run the reference check
described above against it. Until I do, this is a reproducible score change, not an established defect.

Method and limits: the in-scope/out-of-scope split is static analysis of what each scorer reads off
`TaskState`, so a scorer delegating to a module-level helper hides its accesses — 5 of the 54
verdicts came from a wider module scan and are weaker, and 4 were undetermined.

Separately, a pre-registered run over 18 evals gives the applicability census, whose blockers are
structural rather than a to-do list: a grader model is not repeatable, a container is not offline, an
upstream grading package (`livebench`, `kernelbench`) is not present to probe, and a scorer reading
its answer from a file (`scbench`) has no text cue.

```
Applicability census: 18 evals attempted (pre-registered run, 2026-09-21)

  exercisable         9
  blocked_judge       4
  blocked_sandbox     1
  blocked_upstream    2
  no_surface          2
```

If your scorer is model-graded, this package is the wrong tool — and it will **not** reliably tell
you so. See the precondition below.

## What this does not claim

- Not that your scorer is **valid**. It reports invariance under transformations you declared, nothing more.
- No recall figure, and no general accuracy figure. See the scorecard note above.
- Nothing about security, adversarial robustness, or prompt injection.
- No coverage of model-graded scorers, and **no detection of them** — that is a precondition you meet, not a check it runs.
- Not that a transformation is semantically meaning-preserving; only that it is structurally compliant with its own declaration.
- No generality beyond the class of deterministic scorers tested here.
- It does not decide whether a `FAIL` is a real defect. That depends on what the prompt and docs
  promised, which you declare and it records.
- **Nothing about whose defect it is.** If your scorer ports a published benchmark, it cannot tell a port
  divergence from a faithful reproduction of a defective reference — and only the first is a bug report
  for the port's maintainers. That check is reading another repository, which no probe can do for you.
  It inverted three of the four findings this package was built on.
- It does not read your prompt or docs to infer a contract. Inferring intent needs a model, which would
  put an oracle back in the loop and make every verdict rest on that model's reading.

One integrity limit, stated rather than papered over: nothing stops you seeing a `FAIL` and moving that
invariant into `exclusions` to silence it. The contract hash means a reviewer or CI job can pin what was
declared — it makes silencing visible, not impossible.

## Development

```bash
uv pip install -e ".[dev]"
uv run pytest                              # unit tests and the scorecard
uv run python -m scorecard.summary         # the scorecard tally
uv run ruff check src scorecard tests
uv run mypy src
```

## Licence

MIT.
