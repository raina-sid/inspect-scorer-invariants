"""Comparing two observations of the same pipeline.

Two layers, because the demonstrated defects live at different ones:

    scorer layer   did any per-case verdict move?
    metric layer   did any aggregate metric move?

worldsense is the case that forces the split: its verdicts are byte-identical while ws_accuracy
goes 1.0 -> 0.0. A tool comparing only verdicts cannot see it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Any

from inspect_ai.scorer import INCORRECT

from .contract import Relation, Tolerance

# --------------------------------------------------------------------------------------
# metric layer
# --------------------------------------------------------------------------------------


class MetricChange(Enum):
    UNCHANGED = "unchanged"
    VALUE_MOVED = "value_moved"
    #: finite -> NaN. Samples silently left the denominator.
    BECAME_NAN = "became_nan"
    #: NaN -> finite. A transformation that *rescues* a NaN violates the contract too.
    LEFT_NAN = "left_nan"
    #: the metric is not a scalar, so it is not compared rather than coerced
    NOT_COMPARABLE = "not_comparable"


@dataclass(frozen=True)
class MetricComparison:
    name: str
    before: Any
    after: Any
    change: MetricChange

    @property
    def is_violation(self) -> bool:
        return self.change in (
            MetricChange.VALUE_MOVED,
            MetricChange.BECAME_NAN,
            MetricChange.LEFT_NAN,
        )

    def __str__(self) -> str:
        suffix = "" if self.change is MetricChange.UNCHANGED else f"  [{self.change.value}]"
        return f"{self.name}: {self.before} -> {self.after}{suffix}"


def is_scalar(value: Any) -> bool:
    """True for a real number. `bool` is an int subclass and counts; `str` does not.

    Inspect metrics may return dicts or per-key aggregates, and such a metric must be reported
    NOT_COMPARABLE rather than coerced -- silently treating an unprobed metric as unchanged is
    the exact defect class this package exists to find.
    """
    return isinstance(value, (int, float)) and not isinstance(value, str)


def compare_metric(
    name: str, before: Any, after: Any, tolerance: Tolerance | None = None
) -> MetricComparison:
    """Compare one metric value. Never uses a bare `!=`, because nan != nan is True."""
    if not (is_scalar(before) and is_scalar(after)):
        return MetricComparison(name, before, after, MetricChange.NOT_COMPARABLE)

    b, a = float(before), float(after)
    b_nan, a_nan = math.isnan(b), math.isnan(a)

    if b_nan and a_nan:
        return MetricComparison(name, before, after, MetricChange.UNCHANGED)
    if b_nan:
        return MetricComparison(name, before, after, MetricChange.LEFT_NAN)
    if a_nan:
        return MetricComparison(name, before, after, MetricChange.BECAME_NAN)

    if b == a:
        return MetricComparison(name, before, after, MetricChange.UNCHANGED)
    if tolerance is not None and tolerance.permits(b, a):
        return MetricComparison(name, before, after, MetricChange.UNCHANGED)
    return MetricComparison(name, before, after, MetricChange.VALUE_MOVED)


# --------------------------------------------------------------------------------------
# scorer layer
# --------------------------------------------------------------------------------------


class VerdictChange(Enum):
    UNCHANGED = "unchanged"
    CHANGED = "changed"
    #: STAYS_INCORRECT only: a wrong answer became correct
    LEFT_NEGATIVE_CLASS = "left_negative_class"
    #: the negative class cannot be decided for this Score.value type
    NOT_COMPARABLE = "not_comparable"


@dataclass(frozen=True)
class VerdictComparison:
    case_index: int
    before: Any
    after: Any
    change: VerdictChange

    @property
    def is_violation(self) -> bool:
        return self.change in (VerdictChange.CHANGED, VerdictChange.LEFT_NEGATIVE_CLASS)


def in_negative_class(value: Any) -> bool | None:
    """Is this Score.value a wrong answer? None when undecidable.

    Defined rather than guessed, because Score.value may be a string, a number or a dict. A float
    strictly between 0 and 1 is a partial credit and deliberately undecidable -- guessing a
    threshold would put an unstated judgment inside the tool.
    """
    if isinstance(value, str):
        return value == INCORRECT
    if isinstance(value, bool):
        return value is False
    if isinstance(value, (int, float)):
        f = float(value)
        if math.isnan(f):
            return None
        if f == 0.0:
            return True
        if f == 1.0:
            return False
        return None
    return None


def compare_verdict(
    relation: Relation, case_index: int, before: Any, after: Any
) -> VerdictComparison:
    if relation is Relation.EQUAL:
        change = VerdictChange.UNCHANGED if before == after else VerdictChange.CHANGED
        return VerdictComparison(case_index, before, after, change)

    # STAYS_INCORRECT: only meaningful when the baseline was wrong to begin with
    baseline_negative = in_negative_class(before)
    if baseline_negative is None:
        return VerdictComparison(case_index, before, after, VerdictChange.NOT_COMPARABLE)
    if not baseline_negative:
        # nothing to preserve; the case is not evidence either way
        return VerdictComparison(case_index, before, after, VerdictChange.NOT_COMPARABLE)

    after_negative = in_negative_class(after)
    if after_negative is None:
        return VerdictComparison(case_index, before, after, VerdictChange.NOT_COMPARABLE)
    change = (
        VerdictChange.UNCHANGED if after_negative else VerdictChange.LEFT_NEGATIVE_CLASS
    )
    return VerdictComparison(case_index, before, after, change)


def compare_verdicts(
    relation: Relation, before: list[Any], after: list[Any]
) -> list[VerdictComparison]:
    if len(before) != len(after):
        raise ValueError(
            f"verdict lists differ in length ({len(before)} vs {len(after)}); "
            "case count must be preserved before comparison"
        )
    return [
        compare_verdict(relation, i, b, a) for i, (b, a) in enumerate(zip(before, after))
    ]


def divergent_metrics(comparisons: list[MetricComparison]) -> bool:
    """True when some but not all comparable metrics moved.

    This is the signature of a metric-layer defect rather than a scorer change, and on the
    worldsense fixture it is the only thing separating a silent 1.0 -> 0.0 from a legitimate
    score of zero: accuracy holds at 1.0 in the same results block.
    """
    comparable = [c for c in comparisons if c.change is not MetricChange.NOT_COMPARABLE]
    if len(comparable) < 2:
        return False
    moved = [c for c in comparable if c.is_violation]
    return 0 < len(moved) < len(comparable)
