"""Observed differences between two states of an Inspect evaluation.

Observation is automatic; interpretation is yours. Nothing here decides whether a difference is a
bug, an intended change, or harmless -- it reports what changed, where, and which samples to read.
"""

from .dataset_diff import DatasetDiff, GroupDelta, diff_datasets
from .score_diff import ScoreDiff, ScorerDiff, diff_logs, scoring_model_calls
from .snapshot import SampleRecord, Snapshot, records_from_samples, snapshot_task

__all__ = [
    "DatasetDiff", "GroupDelta", "SampleRecord", "ScoreDiff", "ScorerDiff", "Snapshot",
    "diff_datasets", "diff_logs", "records_from_samples", "scoring_model_calls", "snapshot_task",
]
