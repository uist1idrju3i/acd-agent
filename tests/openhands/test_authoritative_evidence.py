"""Authoritative Evidence verification tests."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import cast

import pytest


def _record() -> dict[str, object]:
    record = json.loads(
        Path("fixtures/contracts/valid/evidence.json").read_text(encoding="utf-8")
    )
    envelope = record["envelope"]
    assert isinstance(envelope, dict)
    record["target_revision"] = "r3"
    envelope["target_revision"] = "r3"
    envelope["execution_context"] = "container"
    envelope["container_image_digest"] = "sha256:" + "a" * 64
    envelope["execution_env"] = "linux-x86_64; container=sha256:" + "a" * 64
    envelope["source_revision"] = "b" * 40
    envelope["source_tree_state"] = "clean"
    envelope["source_dirty_digest"] = None
    return record


def _write(tmp_path: Path, record: dict[str, object]) -> Path:
    path = tmp_path / "evidence.json"
    path.write_text(json.dumps(record), encoding="utf-8")
    return path


def _verify(
    *paths: Path,
    revision: str = "r3",
    revision_from: Path | None = None,
    out_roots: tuple[Path, ...] = (),
    require_lanes: tuple[str, ...] = (),
    source_revision: str | None = None,
    bootstrap_record: Path | None = None,
) -> bool:
    revision_args = (
        ["--revision-from", str(revision_from)]
        if revision_from is not None
        else ["--revision", revision]
    )
    source_args = (
        ["--source-revision", source_revision]
        if source_revision is not None
        else []
    )
    record_args = (
        ["--bootstrap-record", str(bootstrap_record)]
        if bootstrap_record is not None
        else []
    )
    result = subprocess.run(
        [
            sys.executable,
            "scripts/verify_authoritative_evidence.py",
            *revision_args,
            *source_args,
            *record_args,
            *(arg for root in out_roots for arg in ("--out-root", str(root))),
            *(arg for lane in require_lanes for arg in ("--require-lane", lane)),
            *(str(path) for path in paths),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def _write_named(directory: Path, name: str, record: dict[str, object]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(json.dumps(record), encoding="utf-8")
    return path


def test_authoritative_evidence_is_accepted(tmp_path: Path) -> None:
    assert _verify(_write(tmp_path, _record()))


def test_host_evidence_is_rejected(tmp_path: Path) -> None:
    record = _record()
    envelope = record["envelope"]
    assert isinstance(envelope, dict)
    envelope["execution_context"] = "host"
    envelope["container_image_digest"] = None
    envelope["execution_env"] = "linux-x86_64; container=none"
    assert not _verify(_write(tmp_path, record))


def test_revision_and_status_are_rejected(tmp_path: Path) -> None:
    record = _record()
    record["target_revision"] = "r4"
    assert not _verify(_write(tmp_path, record))
    record = _record()
    record["status"] = "stale"
    assert not _verify(_write(tmp_path, record))


def test_unknown_digest_and_malformed_files_are_rejected(tmp_path: Path) -> None:
    record = _record()
    envelope = record["envelope"]
    assert isinstance(envelope, dict)
    envelope["container_image_digest"] = "unknown"
    assert not _verify(_write(tmp_path, record))
    malformed = tmp_path / "malformed.json"
    malformed.write_text("{", encoding="utf-8")
    assert not _verify(malformed)


def test_missing_and_empty_inputs_are_rejected(tmp_path: Path) -> None:
    assert not _verify()
    assert not _verify(tmp_path / "missing.json")


def test_revision_can_be_read_from_design_graph(tmp_path: Path) -> None:
    graph = tmp_path / "graph.json"
    graph.write_text(json.dumps({"revision": "r3"}), encoding="utf-8")
    assert _verify(_write(tmp_path, _record()), revision_from=graph)


@pytest.mark.parametrize(
    "graph_content",
    ["{", "{}", '{"revision": ""}', '{"revision": null}'],
)
def test_invalid_revision_graph_is_rejected(
    tmp_path: Path, graph_content: str
) -> None:
    graph = tmp_path / "graph.json"
    graph.write_text(graph_content, encoding="utf-8")
    assert not _verify(_write(tmp_path, _record()), revision_from=graph)


def test_out_root_collects_nested_lane_evidence(tmp_path: Path) -> None:
    out_root = tmp_path / "out" / "container"
    for lane, sub in (
        ("electrical", "gd1"),
        ("mechanical", "gd1-enclosure"),
        ("firmware", "gd1-fw"),
    ):
        _write_named(out_root / sub, f"evidence-{lane}.json", _record())
    assert _verify(
        out_roots=(out_root,),
        require_lanes=("electrical", "mechanical", "firmware"),
    )


def test_missing_required_lane_is_rejected(tmp_path: Path) -> None:
    out_root = tmp_path / "out"
    _write_named(out_root / "gd1", "evidence-electrical.json", _record())
    _write_named(
        out_root / "gd1-enclosure", "evidence-mechanical.json", _record()
    )
    assert not _verify(
        out_roots=(out_root,),
        require_lanes=("electrical", "mechanical", "firmware"),
    )


def test_nonexistent_and_empty_out_roots_are_rejected(tmp_path: Path) -> None:
    assert not _verify(out_roots=(tmp_path / "missing",))
    empty = tmp_path / "empty"
    empty.mkdir()
    assert not _verify(out_roots=(empty,))


def test_stage_cache_evidence_is_ignored(tmp_path: Path) -> None:
    out_root = tmp_path / "out"
    _write_named(
        out_root / ".stage-cache" / "gd1", "evidence-electrical.json", _record()
    )
    assert not _verify(out_roots=(out_root,), require_lanes=("electrical",))
    _write_named(out_root / "gd1", "evidence-electrical.json", _record())
    assert _verify(out_roots=(out_root,), require_lanes=("electrical",))


def test_revision_sources_cannot_be_combined(tmp_path: Path) -> None:
    graph = tmp_path / "graph.json"
    graph.write_text(json.dumps({"revision": "r3"}), encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            "scripts/verify_authoritative_evidence.py",
            "--revision",
            "r3",
            "--revision-from",
            str(graph),
            str(_write(tmp_path, _record())),
        ],
        check=False,
    )
    assert result.returncode != 0


def test_evidence_without_source_provenance_is_rejected(
    tmp_path: Path,
) -> None:
    record = _record()
    envelope = cast(dict[str, object], record["envelope"])
    envelope.pop("source_revision", None)
    envelope.pop("source_tree_state", None)
    envelope.pop("source_dirty_digest", None)
    assert not _verify(_write(tmp_path, record))


def test_dirty_or_unknown_source_tree_is_rejected(tmp_path: Path) -> None:
    record = _record()
    envelope = cast(dict[str, object], record["envelope"])
    envelope["source_tree_state"] = "dirty"
    envelope["source_dirty_digest"] = "sha256:" + "c" * 64
    assert not _verify(_write(tmp_path, record))

    record = _record()
    envelope = cast(dict[str, object], record["envelope"])
    envelope["source_revision"] = "unknown"
    envelope["source_tree_state"] = "unknown"
    envelope["source_dirty_digest"] = None
    assert not _verify(_write(tmp_path, record))


def test_source_revision_constraint_is_enforced(tmp_path: Path) -> None:
    path = _write(tmp_path, _record())
    assert _verify(path, source_revision="b" * 40)
    assert not _verify(path, source_revision="d" * 40)


def _bootstrap_record(tmp_path: Path, revision: str) -> Path:
    record = tmp_path / "bootstrap-record.json"
    record.write_text(
        json.dumps({"resolved_revision": revision}) + "\n", encoding="utf-8"
    )
    return record


def test_bootstrap_record_source_revision_is_enforced(tmp_path: Path) -> None:
    path = _write(tmp_path, _record())
    assert _verify(path, bootstrap_record=_bootstrap_record(tmp_path, "b" * 40))
    assert not _verify(
        path, bootstrap_record=_bootstrap_record(tmp_path, "d" * 40)
    )


def test_source_revision_must_agree_with_bootstrap_record(tmp_path: Path) -> None:
    path = _write(tmp_path, _record())
    record = _bootstrap_record(tmp_path, "b" * 40)
    assert _verify(path, source_revision="b" * 40, bootstrap_record=record)
    assert not _verify(path, source_revision="d" * 40, bootstrap_record=record)
