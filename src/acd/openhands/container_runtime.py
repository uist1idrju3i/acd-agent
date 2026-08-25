"""Explicit runtime bounds for digest-pinned container execution.

Pinned SDK v1.43.1 runs every docker CLI call of ``DockerWorkspace`` through the
module-level ``execute_command`` helper without a timeout, so ``docker version``,
``docker run``, ``docker inspect``, ``docker logs``, and ``docker stop`` can block
without bound. The helpers here bound those calls, add an explicit container
memory limit, and record the container IDs and timed-out commands observed while
a workspace is running.
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Callable, Generator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Final, Literal, cast

from openhands.workspace.docker import workspace as sdk_docker_workspace

DEFAULT_HEALTH_CHECK_TIMEOUT: Final = 300.0
DEFAULT_COMMAND_TIMEOUT: Final = 3600.0
DEFAULT_DOCKER_CLI_TIMEOUT: Final = 300.0
DEFAULT_MEMORY_LIMIT: Final = "8g"
DEFAULT_PLATFORM: Final = "linux/amd64"
DEFAULT_STOP_TIMEOUT: Final = 60.0

_CONTAINER_ID: Final = re.compile(r"^[0-9a-f]{12,64}$")
_MEMORY_LIMIT: Final = re.compile(r"^[1-9][0-9]*[bkmg]$")
_TIMEOUT_EXIT_CODE: Final = -1
_HEALTH_TIMEOUT_MARKERS: Final = ("failed to become healthy",)

FailureKind = Literal["timeout", "transport", "command"]
DockerCliRunner = Callable[..., subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class ContainerRuntimeConfig:
    """Explicit bounds forwarded to the pinned SDK ``DockerWorkspace``."""

    health_check_timeout: float = DEFAULT_HEALTH_CHECK_TIMEOUT
    command_timeout: float = DEFAULT_COMMAND_TIMEOUT
    docker_cli_timeout: float = DEFAULT_DOCKER_CLI_TIMEOUT
    memory_limit: str = DEFAULT_MEMORY_LIMIT
    platform: str = DEFAULT_PLATFORM
    detach_logs: bool = False

    def __post_init__(self) -> None:
        for name, value in (
            ("health_check_timeout", self.health_check_timeout),
            ("command_timeout", self.command_timeout),
            ("docker_cli_timeout", self.docker_cli_timeout),
        ):
            if value <= 0:
                raise ValueError(f"{name} must be a positive number of seconds")
        if not _MEMORY_LIMIT.fullmatch(self.memory_limit.strip().lower()):
            raise ValueError("memory limit must look like '8g', '512m', or '1024k'")
        if not self.platform.strip():
            raise ValueError("platform must be an explicit docker platform")

    def workspace_kwargs(self) -> dict[str, Any]:
        """Return the explicit ``DockerWorkspace`` constructor arguments."""
        return {
            "health_check_timeout": self.health_check_timeout,
            "platform": self.platform,
            "detach_logs": self.detach_logs,
        }


@dataclass
class DockerCliObservations:
    """Docker CLI facts observed while a workspace was running."""

    timed_out_commands: list[str] = field(default_factory=list[str])
    container_ids: list[str] = field(default_factory=list[str])

    @property
    def timed_out(self) -> bool:
        return bool(self.timed_out_commands)


def _memory_flags(memory_limit: str) -> list[str]:
    limit = memory_limit.strip().lower()
    return [f"--memory={limit}", f"--memory-swap={limit}"]


def _with_memory_limit(
    command: Sequence[str] | str, memory_limit: str
) -> list[str] | str:
    if isinstance(command, str):
        return command
    arguments = list(command)
    if arguments[:2] != ["docker", "run"]:
        return arguments
    return [*arguments[:2], *_memory_flags(memory_limit), *arguments[2:]]


def _record_observation(
    observations: DockerCliObservations,
    command: Sequence[str] | str,
    completed: subprocess.CompletedProcess[str],
) -> None:
    rendered = command if isinstance(command, str) else " ".join(command)
    if completed.returncode == _TIMEOUT_EXIT_CODE:
        observations.timed_out_commands.append(rendered)
        return
    if completed.returncode != 0 or isinstance(command, str):
        return
    if list(command[:2]) != ["docker", "run"]:
        return
    container_id = (completed.stdout or "").strip()
    if _CONTAINER_ID.fullmatch(container_id):
        observations.container_ids.append(container_id)


@contextmanager
def docker_cli_bounds(
    config: ContainerRuntimeConfig,
) -> Generator[DockerCliObservations]:
    """Bound the docker CLI calls the pinned SDK performs for a workspace.

    The pinned SDK resolves ``execute_command`` from its docker workspace module
    at call time, so replacing that attribute for the duration of the workspace
    lifecycle applies the timeout and memory limit to container startup, health
    checks, and cleanup without reimplementing the SDK runner.
    """
    module_globals: dict[str, Any] = sdk_docker_workspace.__dict__
    original = cast(DockerCliRunner, module_globals["execute_command"])
    observations = DockerCliObservations()

    def guarded(
        command: Sequence[str] | str, *args: Any, **kwargs: Any
    ) -> subprocess.CompletedProcess[str]:
        bounded = _with_memory_limit(command, config.memory_limit)
        if len(args) < 3 and "timeout" not in kwargs:
            kwargs["timeout"] = config.docker_cli_timeout
        completed = original(bounded, *args, **kwargs)
        _record_observation(observations, bounded, completed)
        return completed

    module_globals["execute_command"] = guarded
    try:
        yield observations
    finally:
        module_globals["execute_command"] = original


def startup_failure_kind(
    error: BaseException, observations: DockerCliObservations
) -> FailureKind:
    """Classify a workspace startup failure as a timeout or a transport failure."""
    message = str(error).lower()
    if observations.timed_out or any(
        marker in message for marker in _HEALTH_TIMEOUT_MARKERS
    ):
        return "timeout"
    return "transport"


def stop_containers(
    container_ids: Sequence[str],
    *,
    timeout: float = DEFAULT_STOP_TIMEOUT,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> tuple[str, ...]:
    """Stop the given containers and return the IDs that could not be stopped."""
    unstopped: list[str] = []
    for container_id in container_ids:
        try:
            completed = run(
                ["docker", "stop", "--time", "10", container_id],
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout,
            )
        except (OSError, subprocess.TimeoutExpired):
            unstopped.append(container_id)
            continue
        if completed.returncode != 0:
            unstopped.append(container_id)
    return tuple(unstopped)
