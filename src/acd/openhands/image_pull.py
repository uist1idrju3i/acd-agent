"""Pull digest-pinned images declared in the repository image lock.

The pull entry is deterministic: it only pulls ``image@digest`` references taken
from the lock, bounds every docker CLI call with an explicit timeout, retries a
bounded number of times, verifies the local digest after the pull, and returns a
provenance record of what was pulled.
"""

from __future__ import annotations

import json
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, Literal, cast

from acd.openhands.image_lock import ImageDigestLock, load_image_lock, pinned_reference

DEFAULT_PULL_TIMEOUT: Final = 900.0
DEFAULT_INSPECT_TIMEOUT: Final = 60.0
DEFAULT_MAX_ATTEMPTS: Final = 3
DEFAULT_BACKOFF_SECONDS: Final = 5.0

LOCK_ENTRIES: Final = ("acd-tools", "acd-server")

PullFailureKind = Literal[
    "timeout",
    "transport",
    "retry_exhausted",
    "digest_mismatch",
    "lock",
]


class ImagePullError(RuntimeError):
    """A digest-pinned pull could not be completed."""

    def __init__(self, message: str, *, failure_kind: PullFailureKind) -> None:
        super().__init__(message)
        self.failure_kind = failure_kind


@dataclass(frozen=True)
class PullAttempt:
    """One docker pull invocation."""

    attempt: int
    exit_code: int
    timed_out: bool
    stderr: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "attempt": self.attempt,
            "exit_code": self.exit_code,
            "timed_out": self.timed_out,
            "stderr": self.stderr.strip(),
        }


@dataclass(frozen=True)
class PullRecord:
    """Provenance of a completed digest-pinned pull."""

    entry: str
    image: str
    digest: str
    reference: str
    lock_source: str
    docker_version: str
    pull_timeout_seconds: float
    max_attempts: int
    attempts: tuple[PullAttempt, ...]
    pulled_at: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "entry": self.entry,
            "image": self.image,
            "digest": self.digest,
            "reference": self.reference,
            "lock_source": self.lock_source,
            "tool": "docker",
            "docker_version": self.docker_version,
            "pull_timeout_seconds": self.pull_timeout_seconds,
            "max_attempts": self.max_attempts,
            "attempts": [attempt.as_dict() for attempt in self.attempts],
            "pulled_at": self.pulled_at,
        }


def _lock_entry(lock: ImageDigestLock, entry: str) -> tuple[str, str]:
    entries = {"acd-tools": lock.acd_tools, "acd-server": lock.acd_server}
    if entry not in entries:
        raise ImagePullError(f"unknown image lock entry: {entry}", failure_kind="lock")
    published = entries[entry]
    if published is None:
        raise ImagePullError(f"image lock entry is unset: {entry}", failure_kind="lock")
    return pinned_reference(published), published.digest


def _run_docker(
    arguments: list[str],
    *,
    timeout: float,
    run: Callable[..., subprocess.CompletedProcess[str]],
) -> subprocess.CompletedProcess[str] | None:
    """Run a docker command, returning ``None`` when it exceeded the timeout."""
    try:
        return run(
            ["docker", *arguments],
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return None
    except (OSError, ValueError) as exc:
        raise ImagePullError(
            f"docker CLI is unavailable: {exc}", failure_kind="transport"
        ) from exc


def _docker_version(
    *,
    timeout: float,
    run: Callable[..., subprocess.CompletedProcess[str]],
) -> str:
    completed = _run_docker(
        ["version", "--format", "{{.Server.Version}}"], timeout=timeout, run=run
    )
    if completed is None:
        raise ImagePullError(
            f"docker version exceeded {timeout} seconds", failure_kind="timeout"
        )
    version = completed.stdout.strip()
    if completed.returncode != 0 or not version:
        raise ImagePullError(
            "docker server version could not be read; refusing to pull",
            failure_kind="transport",
        )
    return version


def _verify_local_digest(
    reference: str,
    digest: str,
    *,
    timeout: float,
    run: Callable[..., subprocess.CompletedProcess[str]],
) -> None:
    completed = _run_docker(
        ["image", "inspect", "--format={{json .RepoDigests}}", reference],
        timeout=timeout,
        run=run,
    )
    if completed is None:
        raise ImagePullError(
            f"docker image inspect exceeded {timeout} seconds", failure_kind="timeout"
        )
    if completed.returncode != 0:
        raise ImagePullError(
            f"pulled image could not be inspected: {reference}",
            failure_kind="transport",
        )
    try:
        payload: object = json.loads(completed.stdout or "null")
    except json.JSONDecodeError as exc:
        raise ImagePullError(
            f"docker image inspect returned unreadable output: {exc}",
            failure_kind="transport",
        ) from exc
    digests: list[str] = []
    if isinstance(payload, list):
        digests = [
            value for value in cast(list[object], payload) if isinstance(value, str)
        ]
    if not any(value.rsplit("@", 1)[-1] == digest for value in digests):
        raise ImagePullError(
            f"pulled image digest does not match the lock: {reference}",
            failure_kind="digest_mismatch",
        )


def pull_locked_image(
    entry: str,
    *,
    lock_path: Path | None = None,
    timeout: float = DEFAULT_PULL_TIMEOUT,
    inspect_timeout: float = DEFAULT_INSPECT_TIMEOUT,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    backoff_seconds: float = DEFAULT_BACKOFF_SECONDS,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> PullRecord:
    """Pull the locked image for ``entry`` and return its pull provenance."""
    if max_attempts < 1:
        raise ImagePullError(
            "max attempts must be at least 1", failure_kind="retry_exhausted"
        )
    if timeout <= 0 or inspect_timeout <= 0 or backoff_seconds < 0:
        raise ImagePullError(
            "pull timeout and backoff must be positive", failure_kind="lock"
        )
    try:
        lock = load_image_lock(lock_path)
    except (OSError, ValueError) as exc:
        raise ImagePullError(str(exc), failure_kind="lock") from exc
    reference, digest = _lock_entry(lock, entry)
    version = _docker_version(timeout=inspect_timeout, run=run)

    attempts: list[PullAttempt] = []
    for attempt in range(1, max_attempts + 1):
        completed = _run_docker(["pull", reference], timeout=timeout, run=run)
        if completed is None:
            attempts.append(
                PullAttempt(
                    attempt=attempt,
                    exit_code=-1,
                    timed_out=True,
                    stderr=f"docker pull exceeded {timeout} seconds",
                )
            )
        else:
            attempts.append(
                PullAttempt(
                    attempt=attempt,
                    exit_code=completed.returncode,
                    timed_out=False,
                    stderr=completed.stderr,
                )
            )
            if completed.returncode == 0:
                _verify_local_digest(
                    reference, digest, timeout=inspect_timeout, run=run
                )
                return PullRecord(
                    entry=entry,
                    image=reference.split("@", 1)[0],
                    digest=digest,
                    reference=reference,
                    lock_source=str(lock_path) if lock_path else "packaged",
                    docker_version=version,
                    pull_timeout_seconds=timeout,
                    max_attempts=max_attempts,
                    attempts=tuple(attempts),
                    pulled_at=now().isoformat(),
                )
        if attempt < max_attempts:
            sleep(backoff_seconds * attempt)

    last = attempts[-1]
    kind: PullFailureKind = "timeout" if last.timed_out else "retry_exhausted"
    raise ImagePullError(
        f"docker pull failed after {max_attempts} attempts: {reference}",
        failure_kind=kind,
    )
