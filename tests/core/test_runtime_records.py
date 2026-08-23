import json
from pathlib import Path

import pytest

from acd.core.runtime_records import (
    StageArtifactCache,
    TimingRecorder,
    write_timing_record,
)


def test_timing_record_is_l3_with_stable_shape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = iter([1.0, 1.25, 2.0, 2.5])
    monkeypatch.setattr("acd.core.runtime_records.time.perf_counter", lambda: next(clock))
    recorder = TimingRecorder()
    recorder.start("first")
    recorder.finish("first")
    recorder.start("second")
    recorder.finish("second")
    path = write_timing_record(tmp_path, recorder)
    body = json.loads(path.read_text(encoding="utf-8"))
    assert body["record_class"] == "L3"
    assert body["pass_evidence"] is False
    assert body["stages"] == [
        {"name": "first", "duration_seconds": 0.25, "start_order": 0},
        {"name": "second", "duration_seconds": 0.5, "start_order": 1},
    ]
    content_hash = body.pop("content_sha256")
    from acd.schema.common import canonical_json_sha256

    assert content_hash == canonical_json_sha256(body)


def test_stage_cache_hit_miss_and_corruption(tmp_path: Path) -> None:
    events: list[dict[str, object]] = []
    cache = StageArtifactCache(tmp_path, events)
    key = StageArtifactCache.key(
        "stage",
        {"graph_revision": "rev", "projection": {"net": "3V3"}},
    )
    assert cache.get("stage", key, ".bin") is None
    cache.put("stage", key, ".bin", b"artifact")
    assert cache.get("stage", key, ".bin") == b"artifact"
    (tmp_path / "stage" / f"{key}.bin").write_bytes(b"corrupt")
    assert cache.get("stage", key, ".bin") is None
    assert [event["status"] for event in events] == ["miss", "stored", "hit", "ignored"]


def test_stage_cache_key_changes_with_inputs() -> None:
    first = StageArtifactCache.key("stage", {"revision": "a"})
    second = StageArtifactCache.key("stage", {"revision": "b"})
    assert first == StageArtifactCache.key("stage", {"revision": "a"})
    assert first != second
