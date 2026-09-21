# inspect-scorer-invariants

Metamorphic invariance probes for [Inspect AI](https://inspect.aisi.org.uk) scoring pipelines.

Existing scorer tests can establish that a scorer behaves correctly on its fixtures. They do not
establish that the **measurement** stays invariant under transformations the task contract treats as
semantically irrelevant.

In a pre-registered run across 18 Inspect evals, a frozen set of such transformations exposed three
previously missed failures, spanning both scorer-level and metric-level behaviour. All three evals
already had scorer tests.

The package answers exactly one question:

> Given a contract **C** and a transformation **T**, does pipeline **P** satisfy **C**?

It does **not** decide whether C is semantically right for the task. That judgment stays with you, is
recorded in the report, and is hashed.

---

## Install

```bash
pip install inspect-scorer-invariants
```

Requires `inspect-ai`. No model providers, no network, no Docker.

## Use

```python
from inspect_ai.scorer import accuracy
from scorer_invariants import Case, Contract, CUE_CASE, MARKUP, assert_invariants, probe

report = probe(
    scorer=my_scorer(),
    metrics=[accuracy(), my_weighted_accuracy()],
    cases=[Case(completion="TRUE", target="TRUE"), Case(completion="FALSE", target="FALSE")],
    contract=Contract(
        invariants=[CUE_CASE],   # I assert the verdict does not depend on answer case
        exclusions=[MARKUP],     # my prompt says "no other text", so markup is out of scope
    ),
)
print(report.render())
assert_invariants(report)
```

`invariants` is required. A probe with no declared contract would have to assume every invariant
holds — which manufactures false positives on any task whose prompt rules one out — or assert nothing
at all.

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

## The five invariants

| invariant | asserts the observation does not depend on |
|---|---|
| `CUE_WHITESPACE` | whitespace around the answer cue |
| `CUE_CASE` | case of the cue or the answer token |
| `MARKUP` | markdown emphasis around the cue or the answer |
| `CODE_FORMATTING` | reindentation, blank lines, hoisted imports, fence-tag case |
| `WRONG_STAYS_INCORRECT` | *(a relation, not equality)* a wrong answer stays wrong when replaced by a differently-wrong answer of the same shape |

`WRONG_STAYS_INCORRECT` ships with **no built-in transformation**, on purpose: "a differently-wrong
answer of the same surface shape" is domain knowledge, and a generic guess would be the library
smuggling an assumption into your test. Supply your own — `scorecard/fixtures.py` has a worked
example.

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

`assert_invariants` raises on `FAIL`, ignores `EXCLUDED` and `NOT_APPLICABLE`, and **warns** on
`ERROR` — a scorer that could not be probed must never read as green. It also fails outright when zero
probes executed, because a contract that observes nothing would otherwise stay green forever.

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

## Repeatability, not determinism

The baseline is observed twice (`repeatability_runs=2`) and the runs must agree, or the whole probe
returns `ERROR(NONREPEATABLE_BASELINE)`. This establishes repeatability across the configured runs —
**not** determinism. A judge at temperature 0, or two lucky draws, would pass it.

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
into `inspect_evals`. These defects should be reported upstream, and if they are fixed a scorecard
calling the real scorers would turn red — doing the right thing would destroy the evidence.

## Coverage: half of the evals attempted could not be probed at all

```
Applicability census: 18 evals attempted (pre-registered run, 2026-09-21)

  exercisable         9
  blocked_judge       4
  blocked_sandbox     1
  blocked_upstream    2
  no_surface          2
```

The reasons are structural, not a to-do list. A scorer that calls a grader model is not repeatable. A
scorer that needs a container cannot run offline. A scorer whose grading logic lives in an upstream pip
package (`livebench`, `kernelbench`) is not present to probe. A scorer that reads its answer from a
file rather than from model prose (`scbench`) has no text cue to perturb. And a structural tool-call
matcher (`bfcl`) has no cue either.

If your scorer is model-graded, this package is the wrong tool and will tell you so rather than guess.

## What this does not claim

- Not that your scorer is **valid**. It reports invariance under transformations you declared, nothing more.
- No recall figure, and no general accuracy figure. See the scorecard note above.
- Nothing about security, adversarial robustness, or prompt injection.
- No coverage of model-graded scorers.
- No generality beyond the class of deterministic scorers tested here.
- It does not decide whether a `FAIL` is a real defect. That depends on what the prompt and docs
  promised, which you declare and it records.
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
