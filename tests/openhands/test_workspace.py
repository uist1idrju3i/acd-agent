"""DockerWorkspace runner tests."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar, cast

import pytest

from acd.openhands import container_runtime
from acd.openhands import workspace as workspace_module


class _FakeWorkspace:
    instances: ClassVar[list[_FakeWorkspace]] = []

    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs
        self.commands: list[tuple[str, str, float]] = []
        self.downloads: list[tuple[str, Path]] = []
        self.__class__.instances.append(self)

    def __enter__(self) -> _FakeWorkspace:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute_command(
        self, command: str, cwd: str, timeout: float
    ) -> SimpleNamespace:
        self.commands.append((command, cwd, timeout))
        return SimpleNamespace(
            exit_code=0, stdout="ok\n", stderr="", timeout_occurred=False
        )

    def file_download(self, source: str, destination: Path) -> SimpleNamespace:
        self.downloads.append((source, destination))
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text("{}", encoding="utf-8")
        return SimpleNamespace(success=True, error=None)


def test_runner_uses_read_only_mount_and_downloads_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _FakeWorkspace.instances.clear()
    def resolve(_image: str, **_kwargs: object) -> workspace_module.ImageReference:
        return workspace_module.ImageReference("sha256:" + "a" * 64, "image ID")

    monkeypatch.setattr(workspace_module, "resolve_image_digest", resolve)
    monkeypatch.delenv("ACD_CONTAINER_IMAGE_DIGEST", raising=False)
    monkeypatch.delenv("ACD_IN_CONTAINER", raising=False)

    result = workspace_module.run_command_in_workspace(
        image="acd-tools-gates:local",
        command="uv run python scripts/run_gd1_pipeline.py",
        repository=tmp_path,
        download_files=(
            "out/gd1/evidence-electrical.json",
            "out/gd1-enclosure/evidence-mechanical.json",
        ),
        workspace_factory=_FakeWorkspace,
    )

    instance = _FakeWorkspace.instances[0]
    assert instance.kwargs["volumes"] == [f"{tmp_path.resolve()}:/acd-src:ro"]
    assert instance.kwargs["server_image"] == "acd-tools-gates:local"
    assert instance.kwargs["forward_env"] == [
        "ACD_CONTAINER_IMAGE_DIGEST",
        "ACD_IN_CONTAINER",
    ]
    command, cwd, timeout = instance.commands[0]
    assert cwd == "/workspace"
    assert timeout == 3600.0
    assert "tar -C /acd-src" in command
    assert "cd /workspace/acd" in command
    assert result.downloaded_files == (
        tmp_path / "out/container/gd1/evidence-electrical.json",
        tmp_path / "out/container/gd1-enclosure/evidence-mechanical.json",
    )
    assert instance.downloads == [
        (
            "/workspace/acd/out/gd1/evidence-electrical.json",
            tmp_path / "out/container/gd1/evidence-electrical.json",
        ),
        (
            "/workspace/acd/out/gd1-enclosure/evidence-mechanical.json",
            tmp_path / "out/container/gd1-enclosure/evidence-mechanical.json",
        ),
    ]
    assert "ACD_CONTAINER_IMAGE_DIGEST" not in workspace_module.os.environ
    assert "ACD_IN_CONTAINER" not in workspace_module.os.environ


def test_runner_forwards_opt_in_cache_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _FakeWorkspace.instances.clear()

    def resolve(_image: str, **_kwargs: object) -> workspace_module.ImageReference:
        return workspace_module.ImageReference("sha256:" + "1" * 64, "image ID")

    monkeypatch.setattr(workspace_module, "resolve_image_digest", resolve)
    monkeypatch.setenv("UV_CACHE_DIR", "previous-uv-cache")
    monkeypatch.setenv("CCACHE_DIR", "previous-ccache")
    cache_dir = tmp_path / "cache"
    workspace_module.run_command_in_workspace(
        image="acd-server:local",
        command="true",
        repository=tmp_path,
        download_files=(),
        cache_dir=cache_dir,
        workspace_factory=_FakeWorkspace,
    )

    instance = _FakeWorkspace.instances[0]
    assert instance.kwargs["volumes"] == [
        f"{tmp_path.resolve()}:/acd-src:ro",
        f"{cache_dir.resolve()}:/opt/acd-cache",
    ]
    assert instance.kwargs["forward_env"] == [
        "ACD_CONTAINER_IMAGE_DIGEST",
        "ACD_IN_CONTAINER",
        "UV_CACHE_DIR",
        "CCACHE_DIR",
    ]
    assert workspace_module.os.environ["UV_CACHE_DIR"] == "previous-uv-cache"
    assert workspace_module.os.environ["CCACHE_DIR"] == "previous-ccache"


def test_runner_refuses_unresolved_digest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def resolve(_image: str, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr(workspace_module, "resolve_image_digest", resolve)
    with pytest.raises(ValueError, match="digest could not be resolved"):
        workspace_module.run_command_in_workspace(
            image="missing:local",
            command="true",
            repository=tmp_path,
            download_files=(),
            workspace_factory=_FakeWorkspace,
        )


def test_runner_refuses_empty_server_image(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def resolve(_image: str, **_kwargs: object) -> workspace_module.ImageReference:
        raise AssertionError("digest resolution must not run for an empty image")

    monkeypatch.setattr(workspace_module, "resolve_image_digest", resolve)
    with pytest.raises(ValueError, match="server image must not be empty"):
        workspace_module.run_command_in_workspace(
            image=" \t",
            command="true",
            repository=tmp_path,
            download_files=(),
            workspace_factory=_FakeWorkspace,
        )


def test_runner_does_not_download_after_command_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _FailingWorkspace(_FakeWorkspace):
        def execute_command(
            self, command: str, cwd: str, timeout: float
        ) -> SimpleNamespace:
            self.commands.append((command, cwd, timeout))
            return SimpleNamespace(
                exit_code=1, stdout="", stderr="failed", timeout_occurred=False
            )

    def resolve(_image: str, **_kwargs: object) -> workspace_module.ImageReference:
        return workspace_module.ImageReference("sha256:" + "b" * 64, "image ID")

    monkeypatch.setattr(workspace_module, "resolve_image_digest", resolve)
    result = workspace_module.run_command_in_workspace(
        image="acd-tools-gates:local",
        command="false",
        repository=tmp_path,
        download_files=(),
        workspace_factory=_FailingWorkspace,
    )
    assert result.downloaded_files == ()


def test_runner_fails_when_evidence_download_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _DownloadFailingWorkspace(_FakeWorkspace):
        def file_download(self, source: str, destination: Path) -> SimpleNamespace:
            self.downloads.append((source, destination))
            return SimpleNamespace(success=False, error="download failed")

    def resolve(_image: str, **_kwargs: object) -> workspace_module.ImageReference:
        return workspace_module.ImageReference("sha256:" + "d" * 64, "image ID")

    monkeypatch.setattr(workspace_module, "resolve_image_digest", resolve)
    with pytest.raises(RuntimeError, match="failed to download workspace file"):
        workspace_module.run_command_in_workspace(
            image="acd-server:local",
            command="true",
            repository=tmp_path,
            download_files=("out/gd1/evidence-electrical.json",),
            workspace_factory=_DownloadFailingWorkspace,
        )


def test_local_runner_uses_local_workspace_as_provisional(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}

    class _LocalWorkspace(_FakeWorkspace):
        def __init__(self, **kwargs: object) -> None:
            super().__init__(**kwargs)
            captured["constructor"] = kwargs

    monkeypatch.delenv("ACD_IN_CONTAINER", raising=False)
    monkeypatch.delenv("ACD_CONTAINER_IMAGE_DIGEST", raising=False)
    result = workspace_module.run_command_in_local_workspace(
        command="echo ok",
        repository=tmp_path,
        workspace_factory=_LocalWorkspace,
    )

    instance = _LocalWorkspace.instances[-1]
    command, cwd, timeout = instance.commands[0]
    assert captured["constructor"] == {"working_dir": tmp_path}
    assert command == "echo ok"
    assert cwd == tmp_path
    assert timeout == 3600.0
    assert result.exit_code == 0
    assert result.execution_context == "host"
    assert result.authoritative is False


@pytest.mark.parametrize("variable", ["ACD_IN_CONTAINER", "ACD_CONTAINER_IMAGE_DIGEST"])
def test_local_runner_rejects_container_provenance(
    variable: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(variable, "configured")
    with pytest.raises(ValueError, match="container provenance"):
        workspace_module.run_command_in_local_workspace(
            command="true",
            repository=tmp_path,
            workspace_factory=_FakeWorkspace,
        )


def test_local_runner_preserves_command_failure_exit_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _FailingWorkspace(_FakeWorkspace):
        def execute_command(
            self, command: str, cwd: str, timeout: float
        ) -> SimpleNamespace:
            self.commands.append((command, cwd, timeout))
            return SimpleNamespace(
                exit_code=7, stdout="", stderr="failed", timeout_occurred=False
            )

    monkeypatch.delenv("ACD_IN_CONTAINER", raising=False)
    monkeypatch.delenv("ACD_CONTAINER_IMAGE_DIGEST", raising=False)
    result = workspace_module.run_command_in_local_workspace(
        command="false",
        repository=tmp_path,
        workspace_factory=_FailingWorkspace,
    )
    assert result.exit_code == 7


def test_bundled_source_runs_image_bundle_without_repository_mount(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _FakeWorkspace.instances.clear()

    def resolve(_image: str, **_kwargs: object) -> workspace_module.ImageReference:
        return workspace_module.ImageReference("sha256:" + "c" * 64, "RepoDigests")

    monkeypatch.setattr(workspace_module, "resolve_image_digest", resolve)
    result = workspace_module.run_command_in_workspace(
        image="acd-server:local",
        command="uv run python scripts/run_gd1_pipeline.py",
        repository=tmp_path,
        download_files=("out/gd1/evidence-electrical.json",),
        workspace_factory=_FakeWorkspace,
        source="bundled",
    )

    instance = _FakeWorkspace.instances[0]
    assert "volumes" not in instance.kwargs
    command, _cwd, _timeout = instance.commands[0]
    assert "tar -C /acd-src" not in command
    assert "test -f /opt/acd/pyproject.toml" in command
    assert "test -d /opt/acd/.venv" in command
    assert "test -d /opt/acd/fixtures" in command
    assert "test -d /opt/acd/contracts" in command
    assert "cd /opt/acd" in command
    assert instance.downloads == [
        (
            "/opt/acd/out/gd1/evidence-electrical.json",
            tmp_path / "out/container/gd1/evidence-electrical.json",
        )
    ]
    assert result.exit_code == 0


def test_bundled_source_stops_when_contracts_are_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _FakeWorkspace.instances.clear()

    def resolve(_image: str, **_kwargs: object) -> workspace_module.ImageReference:
        return workspace_module.ImageReference("sha256:" + "d" * 64, "RepoDigests")

    class _MissingContractsWorkspace(_FakeWorkspace):
        def execute_command(
            self, command: str, cwd: str, timeout: float
        ) -> SimpleNamespace:
            self.commands.append((command, cwd, timeout))
            if "test -d /opt/acd/contracts" in command:
                return SimpleNamespace(
                    exit_code=1,
                    stdout="",
                    stderr="contracts missing",
                    timeout_occurred=False,
                )
            return SimpleNamespace(
            exit_code=0, stdout="ok\n", stderr="", timeout_occurred=False
        )

    monkeypatch.setattr(workspace_module, "resolve_image_digest", resolve)
    result = workspace_module.run_command_in_workspace(
        image="acd-server:local",
        command="uv run python scripts/run_gd1_pipeline.py",
        repository=tmp_path,
        download_files=("out/gd1/evidence-electrical.json",),
        workspace_factory=_MissingContractsWorkspace,
        source="bundled",
    )

    assert result.exit_code == 1
    assert result.downloaded_files == ()
    assert _MissingContractsWorkspace.instances[0].downloads == []


def test_runner_rejects_unknown_workspace_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def resolve(_image: str, **_kwargs: object) -> workspace_module.ImageReference:
        raise AssertionError("digest resolution must not run for an unknown source")

    monkeypatch.setattr(workspace_module, "resolve_image_digest", resolve)
    with pytest.raises(ValueError, match="unknown workspace source"):
        workspace_module.run_command_in_workspace(
            image="acd-server:local",
            command="true",
            repository=tmp_path,
            download_files=(),
            workspace_factory=_FakeWorkspace,
            source="image",  # type: ignore[arg-type]
        )


def test_runner_forwards_explicit_runtime_bounds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _FakeWorkspace.instances.clear()

    def resolve(_image: str, **_kwargs: object) -> workspace_module.ImageReference:
        return workspace_module.ImageReference("sha256:" + "e" * 64, "RepoDigests")

    monkeypatch.setattr(workspace_module, "resolve_image_digest", resolve)
    runtime = container_runtime.ContainerRuntimeConfig(
        health_check_timeout=45.0,
        command_timeout=120.0,
        docker_cli_timeout=30.0,
        memory_limit="4g",
        platform="linux/amd64",
    )
    workspace_module.run_command_in_workspace(
        image="acd-server:local",
        command="true",
        repository=tmp_path,
        download_files=(),
        workspace_factory=_FakeWorkspace,
        runtime=runtime,
    )

    instance = _FakeWorkspace.instances[0]
    assert instance.kwargs["health_check_timeout"] == 45.0
    assert instance.kwargs["platform"] == "linux/amd64"
    assert instance.kwargs["detach_logs"] is False
    assert instance.commands[0][2] == 120.0


def test_runner_stops_containers_when_startup_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def resolve(_image: str, **_kwargs: object) -> workspace_module.ImageReference:
        return workspace_module.ImageReference("sha256:" + "f" * 64, "RepoDigests")

    stopped: list[tuple[str, ...]] = []

    def stop_containers(
        container_ids: object, **_kwargs: object
    ) -> tuple[str, ...]:
        assert isinstance(container_ids, list)
        stopped.append(
            tuple(str(value) for value in cast(list[object], container_ids))
        )
        return ()

    def failing_factory(**_kwargs: object) -> _FakeWorkspace:
        raise RuntimeError("Container failed to become healthy in time")

    monkeypatch.setattr(workspace_module, "resolve_image_digest", resolve)
    monkeypatch.setattr(workspace_module, "stop_containers", stop_containers)
    with pytest.raises(workspace_module.WorkspaceStartupError) as error:
        workspace_module.run_command_in_workspace(
            image="acd-server:local",
            command="true",
            repository=tmp_path,
            download_files=(),
            workspace_factory=failing_factory,
        )

    assert error.value.failure_kind == "timeout"
    assert stopped == [()]
    assert "ACD_IN_CONTAINER" not in workspace_module.os.environ


def test_runner_reports_command_timeout_as_failure_kind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _TimingOutWorkspace(_FakeWorkspace):
        def execute_command(
            self, command: str, cwd: str, timeout: float
        ) -> SimpleNamespace:
            self.commands.append((command, cwd, timeout))
            return SimpleNamespace(
                exit_code=-1, stdout="", stderr="", timeout_occurred=True
            )

    def resolve(_image: str, **_kwargs: object) -> workspace_module.ImageReference:
        return workspace_module.ImageReference("sha256:" + "0" * 64, "RepoDigests")

    monkeypatch.setattr(workspace_module, "resolve_image_digest", resolve)
    result = workspace_module.run_command_in_workspace(
        image="acd-server:local",
        command="sleep 1",
        repository=tmp_path,
        download_files=(),
        workspace_factory=_TimingOutWorkspace,
    )

    assert result.failure_kind == "timeout"
    assert result.exit_code == -1
    assert result.downloaded_files == ()


def test_runner_reports_transport_failure_kind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _TransportFailingWorkspace(_FakeWorkspace):
        def execute_command(
            self, command: str, cwd: str, timeout: float
        ) -> SimpleNamespace:
            self.commands.append((command, cwd, timeout))
            return SimpleNamespace(
                exit_code=-1, stdout="", stderr="connection reset",
                timeout_occurred=False,
            )

    def resolve(_image: str, **_kwargs: object) -> workspace_module.ImageReference:
        return workspace_module.ImageReference("sha256:" + "1" * 64, "RepoDigests")

    monkeypatch.setattr(workspace_module, "resolve_image_digest", resolve)
    result = workspace_module.run_command_in_workspace(
        image="acd-server:local",
        command="true",
        repository=tmp_path,
        download_files=(),
        workspace_factory=_TransportFailingWorkspace,
    )

    assert result.failure_kind == "transport"


def test_runner_retries_evidence_download_before_failing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _FlakyDownloadWorkspace(_FakeWorkspace):
        def __init__(self, **kwargs: object) -> None:
            super().__init__(**kwargs)
            self.attempts = 0

        def file_download(self, source: str, destination: Path) -> SimpleNamespace:
            self.attempts += 1
            self.downloads.append((source, destination))
            if self.attempts < 2:
                return SimpleNamespace(success=False, error="transient")
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text("{}", encoding="utf-8")
            return SimpleNamespace(success=True, error=None)

    def resolve(_image: str, **_kwargs: object) -> workspace_module.ImageReference:
        return workspace_module.ImageReference("sha256:" + "2" * 64, "RepoDigests")

    monkeypatch.setattr(workspace_module, "resolve_image_digest", resolve)
    result = workspace_module.run_command_in_workspace(
        image="acd-server:local",
        command="true",
        repository=tmp_path,
        download_files=("out/gd1/evidence-electrical.json",),
        workspace_factory=_FlakyDownloadWorkspace,
        sleep=lambda _seconds: None,
    )

    assert result.downloaded_files == (
        tmp_path / "out/container/gd1/evidence-electrical.json",
    )


def test_runner_does_not_retry_command_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _CountingWorkspace(_FakeWorkspace):
        def execute_command(
            self, command: str, cwd: str, timeout: float
        ) -> SimpleNamespace:
            self.commands.append((command, cwd, timeout))
            return SimpleNamespace(
                exit_code=3, stdout="", stderr="gate failed", timeout_occurred=False
            )

    def resolve(_image: str, **_kwargs: object) -> workspace_module.ImageReference:
        return workspace_module.ImageReference("sha256:" + "3" * 64, "RepoDigests")

    monkeypatch.setattr(workspace_module, "resolve_image_digest", resolve)
    _CountingWorkspace.instances.clear()
    result = workspace_module.run_command_in_workspace(
        image="acd-server:local",
        command="false",
        repository=tmp_path,
        download_files=(),
        workspace_factory=_CountingWorkspace,
    )

    assert result.failure_kind == "command"
    assert len(_CountingWorkspace.instances[0].commands) == 1
