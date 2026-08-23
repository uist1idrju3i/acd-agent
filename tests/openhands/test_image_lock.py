"""Tests for the published image digest lock."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

import acd.openhands.image_lock as image_lock
from acd.openhands.image_lock import ImageDigestLock, load_image_lock, pinned_reference
from acd.openhands.locked_image_cli import main as locked_image_main

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
LOCK_PATH = REPOSITORY_ROOT / "docker" / "image-digests.json"
SCRIPT_PATH = REPOSITORY_ROOT / "scripts" / "print_locked_image.py"


class _FakeResource:
    def __init__(self, payload: str | Exception) -> None:
        self.payload = payload

    def joinpath(self, name: str) -> _FakeResource:
        assert name == "image-digests.json"
        return self

    def read_text(self, encoding: str = "utf-8") -> str:
        assert encoding == "utf-8"
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


def _patch_packaged_resource(monkeypatch: pytest.MonkeyPatch, payload: str | Exception) -> None:
    def fake_files(_package: Any) -> _FakeResource:
        return _FakeResource(payload)

    monkeypatch.setattr(image_lock.resources, "files", fake_files)


def test_valid_lock_loads_and_is_pinned() -> None:
    lock = load_image_lock(LOCK_PATH)
    assert lock.acd_tools.digest == (
        "sha256:4059a5556440de657a85996cf0436f08f22ef676818694024916c39a1cea0824"
    )
    assert pinned_reference(lock.acd_tools) == (
        "ghcr.io/uist1idrju3i/acd-tools@"
        "sha256:4059a5556440de657a85996cf0436f08f22ef676818694024916c39a1cea0824"
    )


def test_packaged_lock_loads_without_repository_path(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_packaged_resource(monkeypatch, LOCK_PATH.read_text(encoding="utf-8"))
    lock = load_image_lock()
    assert lock.acd_tools.digest.endswith("1cea0824")


def test_packaged_lock_missing_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_packaged_resource(monkeypatch, FileNotFoundError("missing"))
    with pytest.raises(ValueError, match="packaged image lock unavailable"):
        load_image_lock()


def test_packaged_lock_invalid_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_packaged_resource(monkeypatch, "{")
    with pytest.raises(ValueError, match="invalid image lock"):
        load_image_lock()


def test_digest_matches_sha256_format() -> None:
    lock = load_image_lock(LOCK_PATH)
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", lock.acd_tools.digest)


def test_placeholder_digest_is_rejected() -> None:
    payload = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    payload["acd_tools"]["digest"] = "sha256:" + "0" * 64
    with pytest.raises(ValidationError):
        ImageDigestLock.model_validate(payload)


def test_unknown_field_is_rejected() -> None:
    payload = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    payload["acd_tools"]["unexpected"] = "value"
    with pytest.raises(ValidationError):
        ImageDigestLock.model_validate(payload)


def test_malformed_json_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "image-digests.json"
    path.write_text("{", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid image lock"):
        load_image_lock(path)


def test_print_locked_image_fails_closed_for_unset_server(tmp_path: Path) -> None:
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    lock.pop("acd_server")
    path = tmp_path / "image-digests.json"
    path.write_text(json.dumps(lock), encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--entry",
            "acd-server",
            "--lock",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "unset" in result.stderr


def test_print_locked_image_returns_pinned_server_reference() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--entry",
            "acd-server",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == (
        "ghcr.io/uist1idrju3i/acd-server@"
        "sha256:d055bfc34a205cc618bdd86879ac81e9efd10913161076927c5b951f5035410a"
    )


def test_installed_cli_fails_closed_for_unset_server(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    lock["acd_server"] = None
    path = tmp_path / "image-digests.json"
    path.write_text(json.dumps(lock), encoding="utf-8")
    assert locked_image_main(["--entry", "acd-server", "--lock", str(path)]) == 2
    assert "unset" in capsys.readouterr().err


def test_installed_cli_reads_packaged_lock(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _patch_packaged_resource(monkeypatch, LOCK_PATH.read_text(encoding="utf-8"))
    assert locked_image_main(["--entry", "acd-server"]) == 0
    assert capsys.readouterr().out.strip().startswith("ghcr.io/uist1idrju3i/acd-server@")


def test_installed_cli_fails_closed_for_invalid_lock(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "image-digests.json"
    path.write_text("{", encoding="utf-8")
    assert locked_image_main(["--entry", "acd-server", "--lock", str(path)]) == 2
    assert "invalid image lock" in capsys.readouterr().err
