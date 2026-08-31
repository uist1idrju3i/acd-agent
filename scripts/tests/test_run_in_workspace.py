"""Tests for the Docker workspace gate runner."""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path
from typing import Any

import pytest
import scripts.run_in_workspace as runner_script

from acd.openhands import workspace as workspace_module
from acd.openhands.workspace import (
    ImageReference,
    ProvisionalWorkspaceResult,
    WorkspaceResult,
    WorkspaceTransportError,
    resolve_image_digest,
    run_command_in_workspace,
)
from acd.schema.host_resources import HostResourceReport


@pytest.fixture(autouse=True)
def pass_host_resource_preflight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # pyright: ignore[reportUnusedFunction]
    report = HostResourceReport(
        status="pass",
        mem_total_bytes=16 * 1024**3,
        mem_available_bytes=16 * 1024**3,
        swap_total_bytes=0,
        swap_free_bytes=0,
        cpu_count=4,
        disk_free_bytes=16 * 1024**3,
        requested_memory_limit_bytes=8 * 1024**3,
        declared_jvm_max_heap="2g",
        findings=[],
    )
    def check_resources(*_args: object, **_kwargs: object) -> HostResourceReport:
        return report

    monkeypatch.setattr(workspace_module, "check_host_resources", check_resources)


def _completed(stdout: str, returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["docker"],
        returncode=returncode,
        stdout=stdout,
        stderr="inspect failed" if returncode else "",
    )


def test_resolve_repo_digest() -> None:
    calls: list[list[str]] = []

    def run(command: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return _completed('["registry.example/acd@sha256:' + "a" * 64 + '"]')

    assert resolve_image_digest("acd:local", run=run) == ImageReference(
        "sha256:" + "a" * 64, "RepoDigests"
    )
    assert len(calls) == 1


def test_resolve_image_id_when_repo_digest_is_absent() -> None:
    responses = iter([_completed("[]"), _completed("sha256:" + "b" * 64)])

    def run(command: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        return next(responses)

    assert resolve_image_digest("acd:local", run=run) == ImageReference(
        "sha256:" + "b" * 64, "image ID"
    )


def test_resolve_digest_fails_on_inspect_error() -> None:
    def run(command: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        return _completed("", returncode=1)

    assert resolve_image_digest("missing:local", run=run) is None


def test_resolve_digest_fails_when_docker_is_unavailable() -> None:
    def run(command: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError("docker")

    assert resolve_image_digest("acd:local", run=run) is None


def test_unresolved_digest_does_not_start_workspace(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def resolve_none(_image: str, **_kwargs: object) -> ImageReference | None:
        return None

    monkeypatch.setattr(
        "acd.openhands.workspace.resolve_image_digest",
        resolve_none,
    )
    started = False

    def factory(**_: Any) -> Any:
        nonlocal started
        started = True
        return object()

    with pytest.raises(ValueError, match="digest"):
        run_command_in_workspace(
            image="acd:local",
            command="true",
            repository=tmp_path,
            download_files=(),
            workspace_factory=factory,
        )
    assert started is False


def test_digest_is_forwarded_to_workspace(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    reference = ImageReference("sha256:" + "c" * 64, "image ID")

    def resolve_reference(_image: str, **_kwargs: object) -> ImageReference:
        return reference

    monkeypatch.setattr(
        "acd.openhands.workspace.resolve_image_digest",
        resolve_reference,
    )
    captured: dict[str, Any] = {}

    class Workspace:
        def __enter__(self) -> Workspace:
            return self

        def __exit__(self, *args: Any) -> None:
            return None

        def execute_command(
            self, command: str, cwd: str, timeout: float
        ) -> Any:
            captured["command"] = command
            captured["cwd"] = cwd
            captured["timeout"] = timeout
            captured["env"] = os.environ["ACD_CONTAINER_IMAGE_DIGEST"]
            captured["marker"] = os.environ["ACD_IN_CONTAINER"]
            return type(
                "Result",
                (),
                {
                    "exit_code": 0,
                    "stdout": "ok\n",
                    "stderr": "",
                    "timeout_occurred": False,
                },
            )()

    def factory(**kwargs: Any) -> Workspace:
        captured["constructor"] = kwargs
        assert "ACD_CONTAINER_IMAGE_DIGEST" in kwargs["forward_env"]
        assert "ACD_IN_CONTAINER" in kwargs["forward_env"]
        return Workspace()

    result = run_command_in_workspace(
        image="acd:local",
        command="echo ok",
        repository=tmp_path,
        download_files=(),
        workspace_factory=factory,
    )
    assert result.exit_code == 0
    assert captured["cwd"] == "/workspace"
    assert captured["env"] == reference.digest
    assert captured["marker"] == "1"


def test_cli_requires_server_image() -> None:
    with pytest.raises(SystemExit, match="2"):
        runner_script.main(["true"])


def test_cli_preserves_command_failure_exit_code(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    result = WorkspaceResult(
        digest="sha256:" + "e" * 64,
        source="image ID",
        exit_code=7,
        stdout="",
        stderr="command failed\n",
        downloaded_files=(),
    )

    def fake_run_command(**_kwargs: Any) -> WorkspaceResult:
        return result

    monkeypatch.setattr(
        runner_script,
        "run_command_in_workspace",
        fake_run_command,
    )
    assert (
        runner_script.main(
            [
                "--image",
                "acd-server:local",
                "--repo",
                str(tmp_path),
                "--download",
                "out/gd1/evidence-electrical.json",
                "false",
            ]
        )
        == 7
    )


def test_cli_preserves_command_output_on_transport_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    error = WorkspaceTransportError(
        "missing evidence",
        exit_code=0,
        stdout="lane output\n",
        stderr="lane warning\n",
        downloaded_files=(tmp_path / "out/container/partial.json",),
    )

    def fail_run_command(**_kwargs: Any) -> WorkspaceResult:
        raise error

    monkeypatch.setattr(runner_script, "run_command_in_workspace", fail_run_command)
    assert (
        runner_script.main(
            [
                "--image",
                "acd-server:local",
                "--repo",
                str(tmp_path),
                "--download",
                "out/gd1/evidence-electrical.json",
                "true",
            ]
        )
        == 2
    )
    captured = capsys.readouterr()
    assert "exit code: 0" in captured.out
    assert "stdout:\nlane output\n" in captured.out
    assert "stderr:\nlane warning\n" in captured.out
    assert f"downloaded: {tmp_path / 'out/container/partial.json'}" in captured.out
    assert "workspace failure (transport): missing evidence" in captured.err


def test_cli_local_provisional_is_explicit_opt_in(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    result = ProvisionalWorkspaceResult(exit_code=0, stdout="ok\n", stderr="")
    captured: dict[str, Any] = {}

    def fake_run(**kwargs: Any) -> ProvisionalWorkspaceResult:
        captured.update(kwargs)
        return result

    monkeypatch.delenv("ACD_CONTAINER_IMAGE", raising=False)
    monkeypatch.setattr(runner_script, "run_command_in_local_workspace", fake_run)
    assert (
        runner_script.main(
            [
                "--local-provisional",
                "--repo",
                str(tmp_path),
                "--download",
                "out/gd1/evidence-electrical.json",
                "echo ok",
            ]
        )
        == 0
    )
    assert captured == {"command": "echo ok", "repository": tmp_path}


def test_cli_rejects_local_provisional_with_image(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="2"):
        runner_script.main(
            ["--local-provisional", "--image", "acd-server:local", "--repo", str(tmp_path)]
        )


def test_cli_rejects_local_provisional_with_host_resource_report(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="2"):
        runner_script.main(
            [
                "--local-provisional",
                "--host-resource-report",
                str(tmp_path / "host.json"),
                "true",
            ]
        )


def test_cli_forwards_cache_directory_and_creates_subdirectories(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: dict[str, Any] = {}
    cache_dir = tmp_path / "cache"

    def fake_run_command(**kwargs: Any) -> WorkspaceResult:
        captured.update(kwargs)
        return WorkspaceResult(
            digest="sha256:" + "a" * 64,
            source="image ID",
            exit_code=0,
            stdout="",
            stderr="",
            downloaded_files=(),
        )

    monkeypatch.setattr(runner_script, "run_command_in_workspace", fake_run_command)
    assert (
        runner_script.main(
            [
                "--image",
                "acd-server:local",
                "--repo",
                str(tmp_path),
                "--cache-dir",
                str(cache_dir),
                "--download",
                "out/gd1/evidence-electrical.json",
                "true",
            ]
        )
        == 0
    )
    assert captured["cache_dir"] == cache_dir
    assert (cache_dir / "uv").is_dir()
    assert (cache_dir / "ccache").is_dir()


def _prepare_cache_dir(cache_dir: Path) -> None:
    runner_script._prepare_cache_dir(cache_dir)  # pyright: ignore[reportPrivateUsage]


def test_prepare_cache_dir_normalizes_nested_permissions(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    nested_dir = cache_dir / "uv" / "sdists-v9" / "nested"
    nested_dir.mkdir(parents=True)
    nested_file = nested_dir / "archive"
    nested_file.write_text("cache", encoding="utf-8")
    nested_dir.chmod(0o700)
    nested_file.chmod(0o600)

    _prepare_cache_dir(cache_dir)

    assert nested_dir.stat().st_mode & stat.S_IRWXO == stat.S_IRWXO
    assert nested_file.stat().st_mode & (stat.S_IROTH | stat.S_IWOTH) == (
        stat.S_IROTH | stat.S_IWOTH
    )


def test_prepare_cache_dir_skips_symlink_targets(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    target = tmp_path / "target"
    target.write_text("cache", encoding="utf-8")
    target.chmod(0o600)
    link = cache_dir / "link"
    link.symlink_to(target)

    _prepare_cache_dir(cache_dir)

    assert link.is_symlink()
    assert target.stat().st_mode & 0o777 == 0o600


def test_prepare_cache_dir_creates_top_level_cache_directories(
    tmp_path: Path,
) -> None:
    cache_dir = tmp_path / "cache"

    _prepare_cache_dir(cache_dir)

    assert cache_dir.is_dir()
    assert (cache_dir / "uv").is_dir()
    assert (cache_dir / "ccache").is_dir()


def test_cli_writes_host_resource_report(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    report = HostResourceReport(
        status="pass",
        mem_total_bytes=16 * 1024**3,
        mem_available_bytes=16 * 1024**3,
        swap_total_bytes=0,
        swap_free_bytes=0,
        cpu_count=4,
        disk_free_bytes=16 * 1024**3,
        requested_memory_limit_bytes=8 * 1024**3,
        declared_jvm_max_heap="2g",
        findings=[],
    )
    result = WorkspaceResult(
        digest="sha256:" + "a" * 64,
        source="image ID",
        exit_code=0,
        stdout="",
        stderr="",
        downloaded_files=(),
        host_resource_report=report,
    )

    def run_workspace(**_kwargs: object) -> WorkspaceResult:
        return result

    monkeypatch.setattr(runner_script, "run_command_in_workspace", run_workspace)
    report_path = tmp_path / "reports" / "host.json"
    assert (
        runner_script.main(
            [
                "--image",
                "acd-server:local",
                "--repo",
                str(tmp_path),
                "--host-resource-report",
                str(report_path),
                "--download",
                "out/gd1/evidence-electrical.json",
                "true",
            ]
        )
        == 0
    )
    assert HostResourceReport.model_validate_json(report_path.read_text()) == report


def test_cli_rejects_cache_directory_for_local_provisional(
    tmp_path: Path,
) -> None:
    with pytest.raises(SystemExit, match="2"):
        runner_script.main(
            [
                "--local-provisional",
                "--cache-dir",
                str(tmp_path / "cache"),
                "true",
            ]
        )


def test_cli_forwards_bundled_source(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: dict[str, Any] = {}

    def fake_run_command(**kwargs: Any) -> WorkspaceResult:
        captured.update(kwargs)
        return WorkspaceResult(
            digest="sha256:" + "f" * 64,
            source="RepoDigests",
            exit_code=0,
            stdout="",
            stderr="",
            downloaded_files=(),
        )

    monkeypatch.setattr(runner_script, "run_command_in_workspace", fake_run_command)
    exit_code = runner_script.main(
        [
            "--image",
            "acd-server:local",
            "--source",
            "bundled",
            "--repo",
            str(tmp_path),
            "--download",
            "out/gd1/evidence-electrical.json",
            "true",
        ]
    )
    assert exit_code == 0
    assert captured["source"] == "bundled"


def test_cli_rejects_bundled_source_for_host_provisional_run() -> None:
    with pytest.raises(SystemExit, match="2"):
        runner_script.main(["--local-provisional", "--source", "bundled", "true"])
