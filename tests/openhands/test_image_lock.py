"""Tests for the published image digest lock."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from acd.openhands.image_lock import ImageDigestLock, load_image_lock, pinned_reference

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
LOCK_PATH = REPOSITORY_ROOT / "docker" / "image-digests.json"
SCRIPT_PATH = REPOSITORY_ROOT / "scripts" / "print_locked_image.py"


def test_valid_lock_loads_and_is_pinned() -> None:
    lock = load_image_lock(LOCK_PATH)
    assert lock.acd_tools.digest == (
        "sha256:e64405a15e69991063c688a80b4f215bdc3dbfb8b4fb480b3ef3484f017e1395"
    )
    assert pinned_reference(lock.acd_tools) == (
        "ghcr.io/uist1idrju3i/acd-tools@"
        "sha256:e64405a15e69991063c688a80b4f215bdc3dbfb8b4fb480b3ef3484f017e1395"
    )


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
