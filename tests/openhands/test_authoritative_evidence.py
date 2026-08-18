"""Authoritative Evidence verification tests."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


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
    return record


def _write(tmp_path: Path, record: dict[str, object]) -> Path:
    path = tmp_path / "evidence.json"
    path.write_text(json.dumps(record), encoding="utf-8")
    return path


def _verify(*paths: Path, revision: str = "r3") -> bool:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/verify_authoritative_evidence.py",
            "--revision",
            revision,
            *(str(path) for path in paths),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


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
