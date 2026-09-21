"""Vendored minimal reductions of real scoring pipelines.

WHY REDUCTIONS RATHER THAN CALLS INTO inspect_evals.

Two reasons, and the first is the important one. These defects should be reported upstream, and if
they are fixed a scorecard that called the real scorers would turn red -- doing the right thing
would destroy our own evidence. Second, depending on a large eval package would drag in datasets,
network and optional extras that the package deliberately avoids.

Each reduction reproduces ONE mechanism, with the provenance recorded below. WHAT IS AND IS NOT
CLAIMED: these are minimal reproductions of a mechanism, not byte-for-byte reproductions of the
upstream implementation. They do not use the upstream code (worldsense computes with pandas; this
does not), so a future upstream change could leave a fixture reproducing a mechanism that no longer
exists there. The line references are what make that checkable.

One correction to a claim made about this earlier: the upstream worldsense defect was first reported
here as producing NaN. It does not. Measured through real inspect_ai.eval() with the upstream scorer
and metrics, it produces 0.0, and the fixture matches on that value. The NaN came from an erroneous
reimplementation of the mapping, not from the eval.

Verified 2026-09-21 against inspect_evals with inspect_ai 0.3.263.
"""

from __future__ import annotations

import json
import re

from inspect_ai.scorer import (
    CORRECT,
    INCORRECT,
    SampleScore,
    Score,
    Target,
    accuracy,
    metric,
    scorer,
    value_to_float,
)
from inspect_ai.solver import TaskState

from inspect_scorer_probes import Case, Transform, transform
from inspect_scorer_probes.invariants import CUE_CASE, MARKUP, WRONG_STAYS_INCORRECT

PROVENANCE: dict[str, dict[str, str]] = {
    "worldsense": {
        "mechanism": "metric weight table keyed uppercase-only vs an ignore_case=True scorer",
        "source": "inspect_evals/worldsense/_utils.py:45-83, worldsense.py:91-94",
        "observed": "verdicts unchanged; accuracy 1.0 -> 1.0; ws_accuracy 1.0 -> 0.0",
        "how": "verified end to end through inspect_ai.eval(), not a reimplementation",
    },
    "novelty_bench": {
        "mechanism": "unigram-overlap equality over .strip().lower().split() misses markup",
        "source": "inspect_evals/novelty_bench/partition.py:103-110",
        "observed": "distinct_k 1 -> 2 when one of three identical generations is bolded",
        "how": "verified by calling the real _maybe_test_equality and partition_responses",
    },
    "tau2": {
        "mechanism": "unanchored substring test for required information",
        "source": "inspect_evals/tau2/common/scorer.py:112-137",
        "observed": "airline task 3's whole criterion is '4'; 'error code 404' scores CORRECT",
        "how": "verified against the shipped task data through the real scorer",
    },
    "frontierscience": {
        "mechanism": "VERDICT regex admits digits only; the prompt says 'no other text'",
        "source": "inspect_evals/frontierscience/frontierscience.py:100,210",
        "observed": "'VERDICT: **8**' scores 0.0 instead of 0.8 -- CONTRACT-EXCLUDED, not a defect",
        "how": "the eval's own test asserts the strictness at tests/frontierscience:290",
    },
    "core_choice": {
        "mechanism": "core answer()/parse_answers char class [A-Za-z\\d ,]+ rejects markup",
        "source": "inspect_ai/solver/_multiple_choice.py:98,108",
        "observed": "'ANSWER: **B**' -> INCORRECT -- a CORE property, excluded from scope",
        "how": "verified directly against core answer('letter')",
    },
    "scbench": {
        "mechanism": "answer parsed as JSON under a mandated 'Return EXACTLY' layout",
        "source": "inspect_evals/scbench/scorer.py:27-31, data/evals_canonical/*.json",
        "observed": "markup breaks the JSON parse -- CONTRACT-EXCLUDED; all 30 prompts mandate it",
        "how": "grepped 'Return EXACTLY' across all 30 canonical samples",
    },
}


# --------------------------------------------------------------------------------------
# POSITIVE 1 -- worldsense: the metric-layer defect
# --------------------------------------------------------------------------------------

_WS_WEIGHT = {
    "1": 0.25, "2": 0.25, "3": 0.5,
    "TRUE": 0.5, "FALSE": 0.5, "POSSIBLE": 0.5, "IMPOSSIBLE": 0.5,
}
_WS_PATTERN = r"^\(?\s*(1|2|3|TRUE|FALSE|IMPOSSIBLE|POSSIBLE)\s*\)?"


@scorer(metrics=[accuracy()])
def worldsense_scorer_reduction():
    """Case-INSENSITIVE match that stores the raw matched token as Score.answer.

    This is the half the real eval gets right: `pattern(..., ignore_case=True)` accepts "True"
    just as happily as "TRUE", and records whatever the model wrote.
    """

    async def score(state: TaskState, target: Target) -> Score:
        match = re.search(_WS_PATTERN, state.output.completion.strip(), re.IGNORECASE)
        answer = match.group(1) if match else None
        correct = answer is not None and answer.upper() == target.text.upper()
        return Score(value=CORRECT if correct else INCORRECT, answer=answer)

    return score


@metric
def ws_accuracy_reduction():
    """Weighted accuracy whose weight table is keyed UPPERCASE-only.

    The laundering is the point and is reproduced exactly. In the real eval the unkeyable answers
    become NaN weights; pandas' sum skips NaN and yields 0.0 for an all-NaN group; then the
    divide-by-zero guard (`_utils.py:78-83`) substitutes 1. So "no usable data" surfaces as a
    score of exactly 0.0 -- indistinguishable from a model that got everything wrong -- and
    nothing raises.
    """

    to_float = value_to_float()

    def compute(scores: list[SampleScore]) -> float:
        # the real metric converts the verdict with value_to_float (_utils.py:11); comparing
        # against the CORRECT string instead made this fixture read 0.0 at baseline under
        # inspect_ai.eval(), where the value arrives already converted
        weights = [_WS_WEIGHT.get(s.score.answer or "") for s in scores]
        total = sum(w for w in weights if w is not None)          # NaN-skipping sum
        earned = sum(
            w * to_float(s.score.value)
            for w, s in zip(weights, scores)
            if w is not None
        )
        return earned / (total if total != 0 else 1)              # divide-by-zero guard

    return compute


#: Bare answer tokens, because worldsense's pattern is ^-anchored and its prompt asks the model to
#: "only respond with one of these possible options". An earlier version of this fixture used
#: "ANSWER: TRUE", which never matched the anchor -- the baseline was already all-INCORRECT, and a
#: probe against a broken baseline measures nothing.
WORLDSENSE_CASES = [
    Case(completion="TRUE", target="TRUE"),
    Case(completion="FALSE", target="FALSE"),
    Case(completion="TRUE", target="TRUE"),
    Case(completion="FALSE", target="FALSE"),
]


# --------------------------------------------------------------------------------------
# POSITIVE 2 -- novelty_bench: markup splits an equivalence class
# --------------------------------------------------------------------------------------

_SHORT_MAX_TOKENS = 5


def _novelty_equivalent(a: str, b: str) -> bool:
    """partition.py:103-110 verbatim in behaviour.

    .strip() and .lower() mean case and surrounding whitespace ARE handled -- which is why this
    fixture passes CUE_CASE. Attached markup survives into the token, so `**amelia**` shares no
    unigram with `amelia`.
    """
    ua, ub = a.strip().lower().split(), b.strip().lower().split()
    longest = max(len(ua), len(ub))
    if longest <= _SHORT_MAX_TOKENS:
        return len(set(ua) & set(ub)) * 2 >= longest
    return a.strip().lower() == b.strip().lower()


def _partition(generations: list[str]) -> list[int]:
    labels: list[int] = []
    representatives: list[str] = []
    for gen in generations:
        for index, rep in enumerate(representatives):
            if _novelty_equivalent(gen, rep):
                labels.append(index)
                break
        else:
            labels.append(len(representatives))
            representatives.append(gen)
    return labels


@scorer(metrics=[accuracy()])
def novelty_scorer_reduction():
    """Score.value is distinct_k: how many equivalence classes the k generations fall into.

    The k generations live in metadata["all_completions"], which is where the real eval keeps
    them (novelty_bench.py:140-141) -- NOT in the completion.
    """

    async def score(state: TaskState, target: Target) -> Score:
        generations = list(state.metadata.get("all_completions", []))
        return Score(value=len(set(_partition(generations))))

    return score


NOVELTY_CASES = [
    Case(
        completion="Amelia",
        target="",
        metadata={"all_completions": ["Amelia", "Amelia", "Amelia"]},
    )
]


def bold_one_generation() -> Transform:
    """Bold the FIRST generation only, inside metadata.

    Declares mutates={"metadata"} because that is where this eval keeps its generations. This is
    the worked example of a caller-supplied transformation addressing a field the builtins do not.
    """

    def apply(case: Case) -> Case | None:
        generations = list((case.metadata or {}).get("all_completions", []))
        if not generations or generations[0].startswith("**"):
            return None
        updated = dict(case.metadata or {})
        updated["all_completions"] = [f"**{generations[0]}**", *generations[1:]]
        return case.with_metadata(updated)

    return transform("bold_one_generation", [MARKUP], ["metadata"], apply)


def upper_one_generation() -> Transform:
    """Upper-case the first generation. Same shape as above, testing CUE_CASE instead."""

    def apply(case: Case) -> Case | None:
        generations = list((case.metadata or {}).get("all_completions", []))
        if not generations or generations[0].isupper():
            return None
        updated = dict(case.metadata or {})
        updated["all_completions"] = [generations[0].upper(), *generations[1:]]
        return case.with_metadata(updated)

    return transform("upper_one_generation", [CUE_CASE], ["metadata"], apply)


# --------------------------------------------------------------------------------------
# POSITIVE 3 -- tau2: an unanchored substring test
# --------------------------------------------------------------------------------------


@scorer(metrics=[accuracy()])
def communicated_info_reduction(required: tuple[str, ...] = ("4",)):
    """`info.lower() in haystack` with no anchoring (common/scorer.py:125).

    The default required value is "4", which is airline task 3's ENTIRE success criterion.
    """

    async def score(state: TaskState, target: Target) -> Score:
        haystack = state.output.completion.lower().replace(",", "")
        missing = [info for info in required if info.lower() not in haystack]
        return Score(value=INCORRECT if missing else CORRECT)

    return score


#: Baseline: a wrong answer -- the agent never communicated "4".
TAU2_CASES = [Case(completion="I cannot help with that request.", target="")]


def differently_wrong_error_code() -> Transform:
    """Replace one wrong answer with a DIFFERENTLY wrong answer of the same shape.

    Both completions fail the task; neither communicates the value 4. The second merely contains
    the character '4' inside an unrelated error code, which is enough for an unanchored substring
    test to call it a success.

    WRONG_STAYS_INCORRECT ships with no builtin transformation on purpose: "a differently-wrong
    answer of the same surface shape" is domain knowledge, and a generic guess at it would be the
    library smuggling in an assumption. This is the worked example.
    """

    def apply(case: Case) -> Case | None:
        if "404" in case.completion:
            return None
        return case.with_completion("Sorry, error code 404 occurred. I cannot help.")

    return transform(
        "differently_wrong_error_code", [WRONG_STAYS_INCORRECT], ["completion"], apply
    )


# --------------------------------------------------------------------------------------
# NEGATIVE -- contract exclusions: real strictness the task contract licenses
# --------------------------------------------------------------------------------------


@scorer(metrics=[accuracy()])
def frontierscience_reduction():
    """`VERDICT:\\s*([\\d.]+)` -- digits only, under a prompt that says "no other text"."""

    async def score(state: TaskState, target: Target) -> Score:
        match = re.search(r"VERDICT:\s*([\d.]+)", state.output.completion, re.IGNORECASE)
        if not match:
            return Score(value=0.0)
        try:
            return Score(value=min(1.0, max(0.0, float(match.group(1)) / 10.0)))
        except ValueError:
            return Score(value=0.0)

    return score


FRONTIERSCIENCE_CASES = [
    Case(completion="Reasoning here.\nVERDICT: 8", target=""),
    Case(completion="Other reasoning.\nVERDICT: 6", target=""),
]


@scorer(metrics=[accuracy()])
def scbench_reduction():
    """The answer is a JSON value inside a mandated `Return EXACTLY` block."""

    async def score(state: TaskState, target: Target) -> Score:
        match = re.search(
            r"<EVAL_ANSWER>\s*(\{.*?\})\s*</EVAL_ANSWER>", state.output.completion, re.DOTALL
        )
        if not match:
            return Score(value=INCORRECT)
        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError:
            return Score(value=INCORRECT)
        chosen = str(payload.get("answer", "")).strip().upper()
        return Score(value=CORRECT if chosen == target.text.upper() else INCORRECT, answer=chosen)

    return score


SCBENCH_CASES = [
    Case(completion='<EVAL_ANSWER>{"answer": "A"}</EVAL_ANSWER>', target="A"),
    Case(completion='<EVAL_ANSWER>{"answer": "B"}</EVAL_ANSWER>', target="B"),
]


def scbench_swap_letter() -> Transform:
    """A differently-wrong letter, for WRONG_STAYS_INCORRECT. Stays wrong -- correctly."""

    def apply(case: Case) -> Case | None:
        if '"Z"' in case.completion:
            return None
        return case.with_completion('<EVAL_ANSWER>{"answer": "Z"}</EVAL_ANSWER>')

    return transform("scbench_swap_letter", [WRONG_STAYS_INCORRECT], ["completion"], apply)


#: Baselines that are already WRONG, so WRONG_STAYS_INCORRECT has something to preserve.
SCBENCH_WRONG_CASES = [
    Case(completion='<EVAL_ANSWER>{"answer": "Q"}</EVAL_ANSWER>', target="A"),
    Case(completion='<EVAL_ANSWER>{"answer": "Q"}</EVAL_ANSWER>', target="B"),
]


# --------------------------------------------------------------------------------------
# NEGATIVE -- genuinely robust: whitespace-tolerant extraction
# --------------------------------------------------------------------------------------


@scorer(metrics=[accuracy()])
def agieval_reduction():
    """`(?i)ANSWER\\s*:\\s*([^\\n]+)` with a .strip() -- tolerant of cue whitespace and case."""

    async def score(state: TaskState, target: Target) -> Score:
        matches = re.findall(r"(?i)ANSWER\s*:\s*([^\n]+)", state.output.completion)
        if not matches:
            return Score(value=INCORRECT)
        answer = matches[-1].strip()
        return Score(value=CORRECT if answer.upper() == target.text.upper() else INCORRECT,
                     answer=answer)

    return score


AGIEVAL_CASES = [
    Case(completion="Some reasoning.\nANSWER: 5", target="5"),
    Case(completion="More reasoning.\nANSWER: 7", target="7"),
]
