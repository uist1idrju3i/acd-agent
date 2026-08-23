"""Shared deterministic helpers for pipeline stage parallelism."""

from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from concurrent.futures import Future, ProcessPoolExecutor
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
    ) as executor:
        futures = [executor.submit(stage) for _, stage in stages]
        return [future.result() for future in futures]


def _import_modules(module_names: tuple[str, ...]) -> None:
    import importlib

    for module_name in module_names:
        importlib.import_module(module_name)


class PipelineStageRunner:
    """Reuse a spawn process pool for one pipeline execution."""

    def __init__(self, workers: int) -> None:
        if workers < 1:
            raise ValueError("pipeline worker count must be at least 1")
        self._workers = workers
        self._executor = (
            ProcessPoolExecutor(
                max_workers=workers,
                mp_context=get_context("spawn"),
            )
            if workers > 1
            else None
        )
        self._warmup_futures: list[Future[None]] = []

    def __enter__(self) -> PipelineStageRunner:
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        if self._executor is not None:
            self._executor.shutdown(wait=True)

    def warm_up(self, modules: Sequence[str]) -> None:
        """Import the requested modules in each worker before CAD stages run."""
        if self._executor is None:
            return
        module_names = tuple(modules)
        self._warmup_futures = [
            self._executor.submit(_import_modules, module_names)
            for _ in range(self._workers)
        ]

    def wait_for_warm_up(self) -> None:
        for future in self._warmup_futures:
            future.result()
        self._warmup_futures.clear()

    def submit_stage(self, stage: Callable[[], object]) -> Future[object]:
        if self._executor is not None:
            return self._executor.submit(stage)
        future: Future[object] = Future()
        try:
            future.set_result(stage())
        except BaseException as exc:
            future.set_exception(exc)
        return future

    def run_ordered_stages(
        self,
        stages: Sequence[tuple[str, Callable[[], object]]],
    ) -> list[object]:
        if self._workers == 1 or len(stages) < 2:
            return [stage() for _, stage in stages]
        futures = [self.submit_stage(stage) for _, stage in stages]
        return [future.result() for future in futures]
