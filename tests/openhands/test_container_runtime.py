"""Container runtime bound tests."""

from __future__ import annotations

import subprocess
from typing import Any

import pytest
from openhands.workspace.docker import workspace as sdk_docker_workspace

from acd.openhands import container_runtime


def _module_globals() -> dict[str, Any]:
    return sdk_docker_workspace.__dict__


def _call_sdk_docker(*args: object, **kwargs: object) -> object:
    runner = _module_globals()["execute_command"]
    assert callable(runner)
    return runner(*args, **kwargs)


def test_config_rejects_non_positive_timeouts() -> None:
    with pytest.raises(ValueError, match="command_timeout"):
        container_runtime.ContainerRuntimeConfig(command_timeout=0.0)


def test_config_rejects_unusable_memory_limit() -> None:
    with pytest.raises(ValueError, match="memory limit"):
        container_runtime.ContainerRuntimeConfig(memory_limit="lots")


def test_config_declares_explicit_workspace_bounds() -> None:
    config = container_runtime.ContainerRuntimeConfig(
        health_check_timeout=12.0, platform="linux/arm64", detach_logs=True
    )
    assert config.workspace_kwargs() == {
        "health_check_timeout": 12.0,
        "platform": "linux/arm64",
        "detach_logs": True,
    }


def test_docker_cli_bounds_adds_timeout_and_memory_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[list[str] | str, float | None]] = []

    def fake_execute(
        cmd: list[str] | str,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
        timeout: float | None = None,
        print_output: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        calls.append((cmd, timeout))
        return subprocess.CompletedProcess(cmd, 0, "a" * 64 + "\n", "")

    monkeypatch.setattr(sdk_docker_workspace, "execute_command", fake_execute)
    config = container_runtime.ContainerRuntimeConfig(
        docker_cli_timeout=7.0, memory_limit="512m"
    )
    with container_runtime.docker_cli_bounds(config) as observations:
        _call_sdk_docker(["docker", "run", "-d", "image"])
        _call_sdk_docker(["docker", "version"])

    assert calls[0] == (
        ["docker", "run", "--memory=512m", "--memory-swap=512m", "-d", "image"],
        7.0,
    )
    assert calls[1] == (["docker", "version"], 7.0)
    assert observations.container_ids == ["a" * 64]
    assert observations.timed_out is False

    _call_sdk_docker(["docker", "version"])
    assert calls[2] == (["docker", "version"], None)


def test_docker_cli_bounds_records_timed_out_commands(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_execute(
        cmd: list[str] | str, **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(cmd, -1, "", "")

    monkeypatch.setattr(sdk_docker_workspace, "execute_command", fake_execute)
    with container_runtime.docker_cli_bounds(
        container_runtime.ContainerRuntimeConfig()
    ) as observations:
        _call_sdk_docker(["docker", "run", "-d", "image"])

    assert observations.timed_out is True
    assert observations.container_ids == []


def test_startup_failure_kind_reports_health_timeout() -> None:
    observations = container_runtime.DockerCliObservations()
    error = RuntimeError("Container failed to become healthy in time")
    assert container_runtime.startup_failure_kind(error, observations) == "timeout"
    assert (
        container_runtime.startup_failure_kind(RuntimeError("no daemon"), observations)
        == "transport"
    )


def test_stop_containers_reports_containers_that_stay_up() -> None:
    def run(
        command: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        if command[-1] == "bad":
            return subprocess.CompletedProcess(command, 1, "", "no such container")
        return subprocess.CompletedProcess(command, 0, "", "")

    assert container_runtime.stop_containers(["good", "bad"], run=run) == ("bad",)


def test_stop_containers_reports_stop_timeout() -> None:
    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(command, 1.0)

    assert container_runtime.stop_containers(["stuck"], run=run) == ("stuck",)
