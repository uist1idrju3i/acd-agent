"""DockerWorkspace runner tests."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar

import pytest

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
        return SimpleNamespace(exit_code=0, stdout="ok\n", stderr="")

    def file_download(self, source: str, destination: Path) -> SimpleNamespace:
        self.downloads.append((source, destination))
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text("{}", encoding="utf-8")
        return SimpleNamespace(success=True, error=None)


def test_runner_uses_read_only_mount_and_downloads_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _FakeWorkspace.instances.clear()
    def resolve(_image: str) -> workspace_module.ImageReference:
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
        tmp_path / "out/gd1/evidence-electrical.json",
        tmp_path / "out/gd1-enclosure/evidence-mechanical.json",
    )
    assert instance.downloads == [
        (
            "/workspace/acd/out/gd1/evidence-electrical.json",
            tmp_path / "out/gd1/evidence-electrical.json",
        ),
        (
            "/workspace/acd/out/gd1-enclosure/evidence-mechanical.json",
            tmp_path / "out/gd1-enclosure/evidence-mechanical.json",
        ),
    ]
    assert "ACD_CONTAINER_IMAGE_DIGEST" not in workspace_module.os.environ
    assert "ACD_IN_CONTAINER" not in workspace_module.os.environ


def test_runner_refuses_unresolved_digest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def resolve(_image: str) -> None:
        return None

    monkeypatch.setattr(workspace_module, "resolve_image_digest", resolve)
    with pytest.raises(ValueError, match="digest could not be resolved"):
        workspace_module.run_command_in_workspace(
            image="missing:local",
            command="true",
            repository=tmp_path,
            workspace_factory=_FakeWorkspace,
        )


def test_runner_refuses_empty_server_image(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def resolve(_image: str) -> workspace_module.ImageReference:
        raise AssertionError("digest resolution must not run for an empty image")

    monkeypatch.setattr(workspace_module, "resolve_image_digest", resolve)
    with pytest.raises(ValueError, match="server image must not be empty"):
        workspace_module.run_command_in_workspace(
            image=" \t",
            command="true",
            repository=tmp_path,
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
            return SimpleNamespace(exit_code=1, stdout="", stderr="failed")

    def resolve(_image: str) -> workspace_module.ImageReference:
        return workspace_module.ImageReference("sha256:" + "b" * 64, "image ID")

    monkeypatch.setattr(workspace_module, "resolve_image_digest", resolve)
    result = workspace_module.run_command_in_workspace(
        image="acd-tools-gates:local",
        command="false",
        repository=tmp_path,
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

    def resolve(_image: str) -> workspace_module.ImageReference:
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
            return SimpleNamespace(exit_code=7, stdout="", stderr="failed")

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

    def resolve(_image: str) -> workspace_module.ImageReference:
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
    assert "cd /opt/acd" in command
    assert instance.downloads == [
        (
            "/opt/acd/out/gd1/evidence-electrical.json",
            tmp_path / "out/gd1/evidence-electrical.json",
        )
    ]
    assert result.exit_code == 0


def test_runner_rejects_unknown_workspace_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def resolve(_image: str) -> workspace_module.ImageReference:
        raise AssertionError("digest resolution must not run for an unknown source")

    monkeypatch.setattr(workspace_module, "resolve_image_digest", resolve)
    with pytest.raises(ValueError, match="unknown workspace source"):
        workspace_module.run_command_in_workspace(
            image="acd-server:local",
            command="true",
            repository=tmp_path,
            workspace_factory=_FakeWorkspace,
            source="image",  # type: ignore[arg-type]
        )
