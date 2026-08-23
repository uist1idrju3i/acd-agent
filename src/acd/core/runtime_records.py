"""L3 runtime timing and artifact-cache observations."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

from acd.schema.common import canonical_json_sha256


@dataclass(frozen=True)
class TimingStage:
    """One measured stage in declaration/start order."""

    name: str
    duration_seconds: float
    start_order: int


class TimingRecorder:
    """Collect wall-clock stage durations for an L3 observation."""

    def __init__(self) -> None:
        self._started: dict[str, tuple[int, float]] = {}
        self._stages: list[TimingStage] = []
        self._next_order = 0
        self._lock = Lock()

    def start(self, name: str) -> None:
        """Start a uniquely named stage."""
        with self._lock:
            if name in self._started:
                raise ValueError(f"timing stage already started: {name}")
            self._started[name] = (self._next_order, time.perf_counter())
            self._next_order += 1

    def finish(self, name: str) -> None:
        """Finish a previously started stage."""
        with self._lock:
            started = self._started.pop(name, None)
            if started is None:
                raise ValueError(f"timing stage was not started: {name}")
            order, started_at = started
            self._stages.append(
                TimingStage(
                    name=name,
                    duration_seconds=round(max(0.0, time.perf_counter() - started_at), 6),
                    start_order=order,
                )
            )

    def stages(self) -> tuple[TimingStage, ...]:
        """Return completed stages in start order."""
        with self._lock:
            if self._started:
                raise ValueError(
                    "timing record has unfinished stages: "
                    + ", ".join(sorted(self._started))
                )
            return tuple(sorted(self._stages, key=lambda stage: stage.start_order))

    def finish_open(self) -> None:
        """Close unfinished stages for a fail-closed runtime observation."""
        with self._lock:
            names = tuple(self._started)
        for name in names:
            self.finish(name)


def write_timing_record(
    out_dir: Path,
    recorder: TimingRecorder,
    *,
    cache_events: tuple[dict[str, object], ...] = (),
    target_revision: str | None = None,
) -> Path:
    """Write a canonical, non-authoritative timing observation."""
    stages = [
        {
            "name": stage.name,
            "duration_seconds": stage.duration_seconds,
            "start_order": stage.start_order,
        }
        for stage in recorder.stages()
    ]
    body: dict[str, object] = {
        "schema_version": "0.1",
        "record_class": "L3",
        "pass_evidence": False,
        "stages": stages,
        "cache_events": list(cache_events),
    }
    if target_revision is not None:
        body["target_revision"] = target_revision
    body["content_sha256"] = canonical_json_sha256(body)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "timing-record.json"
    path.write_text(
        json.dumps(body, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


class StageArtifactCache:
    """Content-addressed cache for deterministic stage artifacts."""

    def __init__(self, root: Path, events: list[dict[str, object]] | None = None) -> None:
        self.root = root
        self.events = events if events is not None else []

    @staticmethod
    def key(stage: str, inputs: object) -> str:
        """Return a path-independent canonical key for stage inputs."""
        return canonical_json_sha256({"stage": stage, "inputs": inputs}).removeprefix(
            "sha256:"
        )

    def get(self, stage: str, key: str, suffix: str) -> bytes | None:
        """Return a verified artifact, ignoring corrupt entries."""
        artifact = self.root / stage / f"{key}{suffix}"
        metadata = self.root / stage / f"{key}.json"
        if not artifact.is_file() or not metadata.is_file():
            self.events.append({"stage": stage, "key": key, "status": "miss"})
            return None
        try:
            record = json.loads(metadata.read_text(encoding="utf-8"))
            data = artifact.read_bytes()
            if (
                record.get("key") != key
                or record.get("stage") != stage
                or record.get("content_sha256")
                != "sha256:" + hashlib.sha256(data).hexdigest()
            ):
                raise ValueError("cache metadata or content hash mismatch")
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            self.events.append(
                {"stage": stage, "key": key, "status": "ignored", "reason": str(exc)}
            )
            return None
        self.events.append({"stage": stage, "key": key, "status": "hit"})
        return data

    def put(self, stage: str, key: str, suffix: str, data: bytes) -> None:
        """Store an artifact and its independently verifiable metadata."""
        directory = self.root / stage
        directory.mkdir(parents=True, exist_ok=True)
        artifact = directory / f"{key}{suffix}"
        metadata = directory / f"{key}.json"
        artifact.write_bytes(data)
        metadata.write_text(
            json.dumps(
                {
                    "schema_version": "0.1",
                    "stage": stage,
                    "key": key,
                    "content_sha256": "sha256:" + hashlib.sha256(data).hexdigest(),
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        self.events.append({"stage": stage, "key": key, "status": "stored"})
