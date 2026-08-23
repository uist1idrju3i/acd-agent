"""Shared deterministic helpers for pipeline stage parallelism."""

from __future__ import annotations

import os
import warnings
from collections.abc import Callable, Sequence
from concurrent.futures import Future, ProcessPoolExecutor
from multiprocessing import get_context
from typing import Any

DEFAULT_PIPELINE_WORKERS = min(os.cpu_count() or 1, 4)
DEFAULT_CAD_STAGE_WORKERS = 1
_WARMUP_TIMEOUT_SECONDS = 30.0


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


def _warm_up_worker(
    module_names: tuple[str, ...],
    barrier: Any,
    timeout: float,
) -> str | None:
    import importlib

    failure: str | None = None
    try:
        for module_name in module_names:
            importlib.import_module(module_name)
    except Exception as exc:
        failure = f"{type(exc).__name__}: {exc}"
    try:
        barrier.wait(timeout=timeout)
    except Exception as exc:
        if failure is None:
            failure = f"barrier {type(exc).__name__}: {exc}"
    return failure


class PipelineStageRunner:
    """Reuse a spawn process pool for one pipeline execution."""

    def __init__(self, workers: int) -> None:
        if workers < 1:
            raise ValueError("pipeline worker count must be at least 1")
        self._workers = workers
        self._manager: Any = None
        self._executor: ProcessPoolExecutor | None = None
        if workers > 1:
            context = get_context("spawn")
            self._manager = context.Manager()
            try:
                self._executor = ProcessPoolExecutor(
                    max_workers=workers,
                    mp_context=context,
                )
            except Exception:
                self._manager.shutdown()
                self._manager = None
                raise
        self._warmup_futures: list[Future[str | None]] = []

    def __enter__(self) -> PipelineStageRunner:
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        if self._executor is not None:
            self._executor.shutdown(wait=True)
        if self._manager is not None:
            self._manager.shutdown()

    def warm_up(self, modules: Sequence[str]) -> None:
        """Import the requested modules in each worker before CAD stages run."""
        if self._executor is None:
            return
        if self._warmup_futures:
            self.wait_for_warm_up()
        module_names = tuple(modules)
        barrier = self._manager.Barrier(self._workers)
        self._warmup_futures = [
            self._executor.submit(
                _warm_up_worker,
                module_names,
                barrier,
                _WARMUP_TIMEOUT_SECONDS,
            )
            for _ in range(self._workers)
        ]

    def wait_for_warm_up(self) -> None:
        failures: list[str] = []
        for future in self._warmup_futures:
            try:
                failure = future.result()
            except Exception as exc:
                failures.append(f"{type(exc).__name__}: {exc}")
            else:
                if failure is not None:
                    failures.append(failure)
        self._warmup_futures.clear()
        for failure in failures:
            warnings.warn(
                f"pipeline CAD module warm-up did not complete: {failure}",
                RuntimeWarning,
                stacklevel=2,
            )

    def submit_stage(self, stage: Callable[[], object]) -> Future[object]:
        if self._executor is not None:
            return self._executor.submit(stage)
        future: Future[object] = Future()
        try:
            future.set_result(stage())
        except Exception as exc:
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
