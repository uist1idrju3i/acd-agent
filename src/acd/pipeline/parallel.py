"""Shared deterministic helpers for pipeline stage parallelism."""

from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context

DEFAULT_PIPELINE_WORKERS = min(os.cpu_count() or 1, 4)


def run_ordered_stages(
    stages: Sequence[tuple[str, Callable[[], object]]],
    workers: int,
) -> list[object]:
    """Run independent stages concurrently while preserving declared order."""
    if workers < 1:
        raise ValueError("pipeline worker count must be at least 1")
    if workers == 1 or len(stages) < 2:
        return [stage() for _, stage in stages]
    with ProcessPoolExecutor(
        max_workers=min(workers, len(stages)),
        mp_context=get_context("spawn"),
    ) as executor:
        futures = [executor.submit(stage) for _, stage in stages]
        return [future.result() for future in futures]


_run_ordered_stages = run_ordered_stages
