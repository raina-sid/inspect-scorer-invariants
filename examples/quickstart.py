"""The README quickstart, as a runnable file.

Uses only the public API of this package and of inspect_ai. No provider, no network, no sandbox.

    python examples/quickstart.py

It builds a scorer that is deliberately fine and a metric that is deliberately not, then shows the
probe locating the defect at the metric layer while the per-case verdicts stay identical.
"""

from inspect_ai.scorer import (
    CORRECT,
    INCORRECT,
    SampleScore,
    Score,
    accuracy,
    metric,
    scorer,
)

from scorer_invariants import (
    CUE_CASE,
    Case,
    Contract,
    InvariantViolation,
    assert_invariants,
    probe,
)


@scorer(metrics=[accuracy()])
def my_scorer():
    """Case-insensitive, and records the raw token the model wrote. This part is fine."""

    async def score(state, target):
        answer = state.output.completion.strip()
        return Score(
            value=CORRECT if answer.upper() == target.text.upper() else INCORRECT,
            answer=answer,
        )

    return score


@metric
def weighted_accuracy():
    """A weight table keyed on UPPERCASE answers only. This part is not fine."""
    weights = {"TRUE": 0.5, "FALSE": 0.5}

    def compute(scores: list[SampleScore]) -> float:
        keyed = [weights.get(s.score.answer or "") for s in scores]
        total = sum(w for w in keyed if w is not None)
        if total == 0:
            return 0.0
        earned = sum(
            w for w, s in zip(keyed, scores) if w is not None and s.score.value == CORRECT
        )
        return earned / total

    return compute


report = probe(
    scorer=my_scorer(),
    metrics={"accuracy": accuracy(), "weighted_accuracy": weighted_accuracy()},
    cases=[
        Case(completion="TRUE", target="TRUE"),
        Case(completion="FALSE", target="FALSE"),
    ],
    # I assert the verdict does not depend on the case of the answer token.
    contract=Contract(invariants=[CUE_CASE]),
)

print(report.render())

try:
    assert_invariants(report)
    print("\nassert_invariants passed.")
except InvariantViolation as exc:
    print(f"\nassert_invariants raised, as it should: {str(exc).splitlines()[0]}")
