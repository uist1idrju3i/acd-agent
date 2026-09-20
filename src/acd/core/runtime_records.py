"""Compatibility re-export.

The implementation lives in ``acd.core.runtime.runtime_records``.
"""

from acd.core.runtime.runtime_records import (
    RuntimeObservationError,
    StageArtifactCache,
    TimingRecorder,
    TimingStage,
    write_loop_summary_record,
    write_timing_record,
)

__all__ = [
    "RuntimeObservationError",
    "StageArtifactCache",
    "TimingRecorder",
    "TimingStage",
    "write_loop_summary_record",
    "write_timing_record",
]
