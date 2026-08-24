"""Deterministic digest-pinned pull entry tests."""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from acd.openhands import image_pull

REPOSITORY_LOCK = Path(__file__).resolve().parents[2] / "docker" / "image-digests.json"


def _lock_digest(entry: str) -> tuple[str, str]:
    payload = json.loads(REPOSITORY_LOCK.read_text(encoding="utf-8"))
    section = payload[entry.replace("-", "_")]
    return section["image"], section["digest"]


def _completed(
    command: list[str], returncode: int, stdout: str = "", stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(command, returncode, stdout, stderr)


class _Docker:
    """Scripted docker CLI double."""

    def __init__(self, *, pull_codes: list[int], repo_digests: list[str]) -> None:
        self.pull_codes = pull_codes
        self.repo_digests = repo_digests
        self.calls: list[tuple[list[str], float | None]] = []

    def __call__(
        self,
        command: list[str],
        *,
        timeout: float | None = None,
        **_kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append((command, timeout))
        if command[1] == "version":
            return _completed(command, 0, "29.0.1\n")
        if command[1] == "pull":
            code = self.pull_codes.pop(0)
            if code == -1:
                raise subprocess.TimeoutExpired(command, timeout or 0.0)
            return _completed(command, code, "", "" if code == 0 else "pull failed")
        if command[1] == "image":
            return _completed(command, 0, json.dumps(self.repo_digests))
        raise AssertionError(f"unexpected docker call: {command}")


def test_pull_uses_digest_reference_and_records_provenance() -> None:
    image, digest = _lock_digest("acd-server")
    docker = _Docker(pull_codes=[0], repo_digests=[f"{image}@{digest}"])

    record = image_pull.pull_locked_image(
        "acd-server",
        lock_path=REPOSITORY_LOCK,
        run=docker,
        sleep=lambda _seconds: None,
        now=lambda: datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
    )

    assert record.reference == f"{image}@{digest}"
    assert record.digest == digest
    assert record.docker_version == "29.0.1"
    assert record.pulled_at == "2026-01-02T03:04:05+00:00"
    assert record.as_dict()["attempts"] == [
        {"attempt": 1, "exit_code": 0, "timed_out": False, "stderr": ""}
    ]
    pull_call = next(call for call in docker.calls if call[0][1] == "pull")
    assert pull_call[0] == ["docker", "pull", f"{image}@{digest}"]
    assert pull_call[1] == image_pull.DEFAULT_PULL_TIMEOUT


def test_pull_retries_before_succeeding() -> None:
    image, digest = _lock_digest("acd-tools")
    docker = _Docker(pull_codes=[1, 0], repo_digests=[f"{image}@{digest}"])
    slept: list[float] = []

    record = image_pull.pull_locked_image(
        "acd-tools",
        lock_path=REPOSITORY_LOCK,
        run=docker,
        sleep=slept.append,
        backoff_seconds=2.0,
    )

    assert len(record.attempts) == 2
    assert slept == [2.0]


def test_pull_fails_closed_when_retries_are_exhausted() -> None:
    image, digest = _lock_digest("acd-tools")
    docker = _Docker(pull_codes=[1, 1, 1], repo_digests=[f"{image}@{digest}"])

    with pytest.raises(image_pull.ImagePullError) as error:
        image_pull.pull_locked_image(
            "acd-tools",
            lock_path=REPOSITORY_LOCK,
            run=docker,
            sleep=lambda _seconds: None,
        )
    assert error.value.failure_kind == "retry_exhausted"


def test_pull_fails_closed_on_pull_timeout() -> None:
    image, digest = _lock_digest("acd-tools")
    docker = _Docker(pull_codes=[-1], repo_digests=[f"{image}@{digest}"])

    with pytest.raises(image_pull.ImagePullError) as error:
        image_pull.pull_locked_image(
            "acd-tools",
            lock_path=REPOSITORY_LOCK,
            run=docker,
            max_attempts=1,
            sleep=lambda _seconds: None,
        )
    assert error.value.failure_kind == "timeout"


def test_pull_fails_closed_on_digest_mismatch() -> None:
    image, _digest = _lock_digest("acd-tools")
    docker = _Docker(
        pull_codes=[0], repo_digests=[f"{image}@sha256:{'1' * 64}"]
    )

    with pytest.raises(image_pull.ImagePullError) as error:
        image_pull.pull_locked_image(
            "acd-tools",
            lock_path=REPOSITORY_LOCK,
            run=docker,
            sleep=lambda _seconds: None,
        )
    assert error.value.failure_kind == "digest_mismatch"


def test_pull_refuses_unknown_lock_entry() -> None:
    with pytest.raises(image_pull.ImagePullError) as error:
        image_pull.pull_locked_image(
            "acd-unknown",
            lock_path=REPOSITORY_LOCK,
            run=lambda *_args, **_kwargs: _completed(["docker"], 0, "29.0.1\n"),
            sleep=lambda _seconds: None,
        )
    assert error.value.failure_kind == "lock"


def test_pull_refuses_when_docker_is_unavailable(tmp_path: Path) -> None:
    def run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        raise OSError("docker not found")

    with pytest.raises(image_pull.ImagePullError) as error:
        image_pull.pull_locked_image(
            "acd-tools",
            lock_path=REPOSITORY_LOCK,
            run=run,
            sleep=lambda _seconds: None,
        )
    assert error.value.failure_kind == "transport"
    assert not list(tmp_path.iterdir())


def test_pull_cli_writes_record_and_returns_zero(tmp_path: Path) -> None:
    from acd.openhands import pull_image_cli

    image, digest = _lock_digest("acd-tools")
    docker = _Docker(pull_codes=[0], repo_digests=[f"{image}@{digest}"])
    record_path = tmp_path / "pull.json"

    def fake_pull(entry: str, **kwargs: object) -> image_pull.PullRecord:
        return image_pull.pull_locked_image(
            entry,
            lock_path=REPOSITORY_LOCK,
            run=docker,
            sleep=lambda _seconds: None,
        )

    original = pull_image_cli.pull_locked_image
    pull_image_cli.pull_locked_image = fake_pull
    try:
        code = pull_image_cli.main(
            ["--entry", "acd-tools", "--record", str(record_path)]
        )
    finally:
        pull_image_cli.pull_locked_image = original

    assert code == 0
    assert json.loads(record_path.read_text(encoding="utf-8"))["digest"] == digest


def test_pull_cli_returns_nonzero_on_failure() -> None:
    from acd.openhands import pull_image_cli

    def fake_pull(_entry: str, **_kwargs: object) -> image_pull.PullRecord:
        raise image_pull.ImagePullError("boom", failure_kind="digest_mismatch")

    original = pull_image_cli.pull_locked_image
    pull_image_cli.pull_locked_image = fake_pull
    try:
        assert pull_image_cli.main(["--entry", "acd-tools"]) == 2
    finally:
        pull_image_cli.pull_locked_image = original
