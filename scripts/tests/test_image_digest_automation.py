"""Tests for image digest lock automation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from scripts.update_image_digest_lock import update_lock
from scripts.verify_image_digest_lock import registry_manifest_digest, verify_lock


class _Response:
    def __init__(self, payload: bytes = b"", digest: str | None = None) -> None:
        self._payload = payload
        self.headers = {"Docker-Content-Digest": digest} if digest else {}

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._payload


def _lock(tmp_path: Path) -> Path:
    path = tmp_path / "image-digests.json"
    path.write_text(
        json.dumps(
            {
                "acd_tools": {
                    "image": "ghcr.io/example/acd-tools",
                    "tag": "latest",
                    "digest": "sha256:" + "1" * 64,
                    "published_at": "2026-01-01T00:00:00Z",
                    "workflow_run": "https://github.com/example/actions/runs/1",
                    "dockerfile": "docker/acd-tools.Dockerfile",
                    "tools": {"uv": "1.0"},
                }
            }
        ),
        encoding="utf-8",
    )
    return path


def test_update_lock_is_deterministic_and_updates_metadata(tmp_path: Path) -> None:
    path = _lock(tmp_path)
    digest = "sha256:" + "2" * 64
    assert update_lock(
        path,
        entry="acd_tools",
        digest=digest,
        published_at="2026-02-02T00:00:00Z",
        workflow_run="https://github.com/example/actions/runs/2",
    )
    first = path.read_bytes()
    assert not update_lock(
        path,
        entry="acd_tools",
        digest=digest,
        published_at="2026-02-02T00:00:00Z",
        workflow_run="https://github.com/example/actions/runs/2",
    )
    assert path.read_bytes() == first


def test_update_lock_rejects_unknown_entry_and_malformed_digest(tmp_path: Path) -> None:
    path = _lock(tmp_path)
    with pytest.raises(ValueError, match="unknown image lock entry"):
        update_lock(path, entry="unknown", digest="sha256:" + "2" * 64)
    with pytest.raises(ValueError, match="non-placeholder"):
        update_lock(path, entry="acd_tools", digest="not-a-digest")


def test_registry_manifest_digest_uses_token_and_head() -> None:
    calls: list[Any] = []

    def opener(request: Any, **_kwargs: object) -> _Response:
        calls.append(request)
        if len(calls) == 1:
            return _Response(b'{"token":"anonymous-token"}')
        return _Response(digest="sha256:" + "3" * 64)

    digest = registry_manifest_digest(
        "ghcr.io/example/acd-tools", "latest", opener=opener
    )
    assert digest == "sha256:" + "3" * 64
    assert calls[1].method == "HEAD"
    assert calls[1].headers["Authorization"] == "Bearer anonymous-token"


def test_verify_lock_passes_and_rejects_mismatch(tmp_path: Path) -> None:
    path = _lock(tmp_path)

    def matching_opener(request: Any, **_kwargs: object) -> _Response:
        if request.get_method() == "GET":
            return _Response(b'{"token":"token"}')
        return _Response(digest="sha256:" + "1" * 64)

    assert verify_lock(path, opener=matching_opener)

    def mismatching_opener(request: Any, **_kwargs: object) -> _Response:
        if request.get_method() == "GET":
            return _Response(b'{"token":"token"}')
        return _Response(digest="sha256:" + "4" * 64)

    assert not verify_lock(path, opener=mismatching_opener)


def test_verify_lock_unknown_network_fails_closed(tmp_path: Path) -> None:
    path = _lock(tmp_path)

    def unavailable(*_args: object, **_kwargs: object) -> _Response:
        raise OSError("offline")

    assert not verify_lock(path, opener=unavailable)
