# Provenance audit — is a scorer defect the port's, or the reference implementation's?

**Date:** 2026-09-22. **Trigger:** a reviewer question — *are we sure this is not an obscure edge case?*
Answering it honestly required a second question I had not asked, and the second one turned out to
matter more.

## The check that was missing

Every eval in `inspect_evals` is a **port** of someone else's benchmark. For a port, the contract is
**fidelity to the reference implementation**, not correctness in the abstract. So a probe FAIL has two
very different causes, and the probe cannot tell them apart:

| cause | who should fix it | what a PR to `inspect_evals` would be asking |
|---|---|---|
| the port diverged from the reference | the port's maintainers | a bug fix — welcome |
| the port faithfully reproduces a defective reference | the benchmark's authors | *diverge from the reference* — correctly rejected |

**The missing step, one line: before calling a FAIL a defect, fetch the reference implementation and
check whether it does the same thing.** It costs one `curl`. I ran it after building a fix, not before.

## Result

Four findings audited. **Three are inherited.** One is the port's own — and it is worse than the
symptom I had been chasing.

| finding | reference | verdict |
|---|---|---|
| `zerobench` — extracted `{...}` group never stripped | authors publish the scoring loop in their README; identical | **inherited** |
| `novelty_bench` — unigram-overlap equality misses markup and punctuation | `novelty-bench@d60518d/src/partition.py:137-143`; identical | **inherited** |
| `tau2` — unanchored substring test for required info | `tau2-bench` `evaluator_communicate.py`; identical, with the authors' own `# TODO` | **inherited** |
| `worldsense` — weighted metrics | `facebookresearch/worldsense` `worldsense/analysis.py`; **three divergences** | **port-introduced** |

### zerobench — inherited

Port, `inspect_evals/zerobench/scorer.py:37,44-45`:

```python
formatted_response = model_response.strip().lower()
pattern = r"\{(.*?)\}"
parsed_answer = re.findall(pattern, formatted_response)[-1]
```

The `.strip()` applies to the whole completion, never to the extracted group, so `{ Paris }` parses as
`' paris '` and fails equality. The reference repo `jonathan-roberts1/zerobench` contains **only a
`README.md`** — no code module — and publishes the scoring loop inline in it:

```python
formatted_response = model_response.strip().lower()
try:
    pattern = r"\{(.*?)\}"
    parsed_answer = re.findall(pattern, formatted_response)[-1]
except IndexError:
    parsed_answer = ''
correct = (
    parsed_answer[:len(ground_truth)].lower() == ground_truth.strip().lower()
    and len(parsed_answer) == len(ground_truth.strip())
)
```

Identical, including the unstripped group. The port is faithful. (The only difference is *where*
`ground_truth` is stripped — line 40 in the port, inside the comparison in the reference. Equivalent.)

### novelty_bench — inherited

Port `partition.py:92-114` (`_maybe_test_equality`) against reference
`novelty-bench@d60518d/src/partition.py:137-143` (`maybe_test_equality`) — the same four lines:

```python
unigram_0 = response_0.strip().lower().split()
unigram_1 = response_1.strip().lower().split()
max_len = max(len(unigram_0), len(unigram_1))
if max_len <= 5:
    common_unigrams = set(unigram_0) & set(unigram_1)
    return len(common_unigrams) * 2 >= max_len
```

Worth recording that the mechanism is broader than the markup case the scorecard fixture uses: because
the split is on whitespace, `Paris` and `Paris.` share no unigram and are judged **non**-equivalent,
which *inflates* the eval's headline diversity count. Still inherited, so still not the port's to fix.

### tau2 — inherited, and the authors know

Port `common/scorer.py:121-127` tests `info.lower() in messages_from_agent`. Reference
`tau2-bench` `src/tau2/evaluator/evaluator_communicate.py`:

```python
if info_str.lower() in message.content.lower().replace(
    ",", ""
):  # TODO: This could be improved!
```

Identical, comment included. Reporting this to `inspect_evals` would be reporting a known limitation of
the reference to people who are not its authors.

**One divergence I did NOT resolve:** the reference iterates `AssistantMessage`s; the port collects
`ChatMessageUser` from `state.messages` (`common/scorer.py:42-53`) and names the result
`messages_from_agent`. The port runs the user simulator as the outer model with the agent in a
sub-state, so the role mapping may well be correct — but I did not verify it. Unchecked, not cleared.

### worldsense — the port's own, and three of them

Reference: `facebookresearch/worldsense`, `worldsense/analysis.py`. All three divergences are in how the
weighted metrics are computed, which `inspect_evals/worldsense/README.md:32-33` presents as the paper's
reported numbers.

**(a) The weight is keyed off the wrong column.**

```python
# reference, analysis.py:222
df['acc_weight'] = df['goldresp'].map(weight_map)   # the GOLD answer

# port, _utils.py:69
score_df["weight"] = score_df["answer"].map(weight_mapping)   # the MODEL's answer
```

The weight is a property of the question's answer space, so in the reference it can never be missing —
`goldresp` is always one of seven canonical strings. In the port it depends on what the model emitted,
so an unmappable answer yields NaN, pandas' NaN-skipping `sum` makes the group weight `0.0`, and the
divide-by-zero guard substitutes 1 — producing exactly `0.0`, silently.

**(b) `resp_map` is dropped, which makes the retained weights incoherent.**

The reference collapses two of the three numeric options into one class before comparing
(`analysis.py:191-199`, used at `:225`):

```python
resp_map = {"TRUE": "TRUE", "FALSE": "FALSE", "POSSIBLE": "POSSIBLE",
            "IMPOSSIBLE": "IMPOSSIBLE", "1": "KNOW", "2": "KNOW", "3": "UNKNOWN"}
df['acc'] = (df['resp'].map(resp_map) == df['goldresp'].map(resp_map)).astype(int)
```

The port has no equivalent: its scorer is `pattern(r"^\(?\s*(1|2|3|TRUE|...)\s*\)?")` exact-matching the
target, and its target is a single literal option (`worldsense.py:101-115`). So **answering `2` when the
gold is `1` is CORRECT in the reference and INCORRECT in the port.**

This is what makes (b) more than a stylistic difference: the port *keeps the reference's weights*
(`"1": 0.25, "2": 0.25, "3": 0.5`), and those weights only make sense under the collapse — 0.25 + 0.25
balances the two ways of reaching KNOW against the one way of reaching UNKNOWN. The port therefore
weights `1` and `2` as one class while scoring them as two.

**(c) The case inconsistency** — the scorer is built with `ignore_case=True`
(`worldsense.py:91-92`, `:171-174`) and `pattern()` stores the raw matched text, while the mapping
tables are keyed uppercase-only. This one has no counterpart in the reference at all: `pattern()` is an
`inspect_ai` scorer, so the case tolerance is introduced by the port. It is also a *symptom* of (a) —
key the weight off the gold answer, as the reference does, and it cannot occur.

The uppercase-only tables themselves **are** inherited (`analysis.py:202-219`). It is the combination
that is new.

## What this does to the earlier claims

- The targeted validation study's headline, **"1 genuine defect / 12 applicable cells"**, was wrong.
  The zerobench FAIL is a faithful reproduction, so the count of defects attributable to `inspect_evals`
  in that study is **0**. The measured `FAIL` is still correct and the data files are unchanged — only
  the attribution was wrong. Corrected in `targeted-study.md`.
- The study recorded a counter-argument about zerobench's README prose ("exact matching even for
  numerical answers") and rejected it. That argument was about the *port's* README. The authors' own
  *code* was the thing to check, and it was published in their README the whole time.
- The scorecard's three "positive defect" fixtures remain valid as **detector** fixtures — the
  mechanisms reproduce and the probes still catch them. What changed is that two of the three are not
  defects anyone should file against `inspect_evals`. `README.md` said they "should be reported
  upstream"; that advice is now qualified per fixture.
- The blind sweep's one finding (`docvqa` captures with `match.groups()[0]` and no `.strip()`, where
  `vqa_rad` strips in the same repo) has **not** had this check run against it. Recorded as unaudited.

## How to reproduce this audit

```bash
curl -sL https://raw.githubusercontent.com/novelty-bench/novelty-bench/d60518d/src/partition.py
curl -sL https://raw.githubusercontent.com/sierra-research/tau2-bench/main/src/tau2/evaluator/evaluator_communicate.py
curl -sL https://raw.githubusercontent.com/jonathan-roberts1/zerobench/main/README.md
curl -sL https://raw.githubusercontent.com/facebookresearch/worldsense/main/worldsense/analysis.py
```

Port side read from `inspect_evals` at upstream `d3c049668`.

## The generalisable lesson

A metamorphic probe answers *"does this scorer preserve what you declared it preserves?"* It does not
answer *"is this scorer wrong?"*, and for a port those come apart. **A declared invariant on a ported
scorer is really a claim about the reference implementation**, so the probe's output is a question for
the benchmark's authors far more often than it is a bug report for the port's maintainers.

Three of four findings here inverted on that distinction. It is now a required step in the workflow
(`README.md`, "What a finding looks like").
