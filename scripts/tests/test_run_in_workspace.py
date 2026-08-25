"""Tests for the Docker workspace gate runner."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

import pytest
import scripts.run_in_workspace as runner_script

from acd.openhands.workspace import (
    ImageReference,
    ProvisionalWorkspaceResult,
    WorkspaceResult,
    resolve_image_digest,
    run_command_in_workspace,
)


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
