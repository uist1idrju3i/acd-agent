"""Compatibility re-export.

The implementation lives in ``acd.core.runtime.parallel``.
"""

from acd.core.runtime.parallel import (
    DEFAULT_CAD_STAGE_WORKERS,
    DEFAULT_PIPELINE_WORKERS,
    STAGE_START_METHOD,
    PipelineStageRunner,
    run_ordered_stages,
)

__all__ = [
    "DEFAULT_CAD_STAGE_WORKERS",
    "DEFAULT_PIPELINE_WORKERS",
    "STAGE_START_METHOD",
    "PipelineStageRunner",
    "run_ordered_stages",
]
