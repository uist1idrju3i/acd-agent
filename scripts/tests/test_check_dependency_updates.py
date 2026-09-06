"""Tests for dependency update checks."""

from __future__ import annotations

from pathlib import Path

import pytest
from scripts.check_dependency_updates import (
    DependencyStatus,
    check_docker_args,
    check_github_actions,
    check_pypi,
    check_submodule,
    render_markdown,
)


def _write_repo(tmp_path: Path, *, pyproject: str, lock: str = "") -> Path:
    (tmp_path / "pyproject.toml").write_text(pyproject, encoding="utf-8")
    (tmp_path / "uv.lock").write_text(lock, encoding="utf-8")
    return tmp_path


def test_pypi_checks_lock_versions_and_skips_uv_sources(tmp_path: Path) -> None:
    root = _write_repo(
        tmp_path,
        pyproject="""\
[project]
dependencies = ["Example_Pkg>=1", "openhands-sdk==1.0"]
[dependency-groups]
dev = ["example-pkg", "pytest"]
[tool.uv.sources]
openhands-sdk = { path = "vendor/sdk", editable = true }
""",
        lock="""\
[[package]]
name = "example-pkg"
version = "1.0.0"
[[package]]
name = "pytest"
version = "9.0.0"
""",
    )
    calls: list[str] = []

    def fetch(url: str) -> dict[str, object]:
        calls.append(url)
        name = url.split("/")[-2]
        return {"info": {"version": {"example-pkg": "1.1.0", "pytest": "9.0.0"}[name]}}

    statuses = check_pypi(root, fetch_json=fetch)
    assert [status.name for status in statuses] == ["example-pkg", "pytest"]
    assert statuses[0].outdated
    assert not statuses[1].outdated
    assert all("openhands-sdk" not in call for call in calls)


def test_github_actions_uses_comment_and_major_precision(tmp_path: Path) -> None:
    workflow = tmp_path / ".github" / "workflows"
    workflow.mkdir(parents=True)
    (workflow / "test.yml").write_text(
        """\
steps:
  - uses: actions/checkout@abc # v4
  - uses: actions/checkout@abc # v4
  - uses: astral-sh/setup-uv@v1.0.0
""",
        encoding="utf-8",
    )

    def tags(url: str) -> list[str]:
        return {
            "https://github.com/actions/checkout": ["v3.0.0", "v4.2.0"],
            "https://github.com/astral-sh/setup-uv": ["v1.1.0", "v2.0.0"],
        }[url]

    statuses = check_github_actions(tmp_path, list_remote_tags=tags)
    assert len(statuses) == 2
    assert statuses[0].current == "v4"
    assert not statuses[0].outdated
    assert statuses[0].source.count("test.yml") == 2
    assert statuses[1].outdated


def test_docker_args_check_semeru_and_qemu_ordering(tmp_path: Path) -> None:
    docker = tmp_path / "docker"
    docker.mkdir()
    (docker / "acd-tools.Dockerfile").write_text(
        """\
ARG FREEROUTING_VERSION=2.3.0
ARG UV_VERSION=0.12.7
ARG ESP_IDF_VERSION=v6.1
ARG QEMU_ESP_TAG=esp-develop-9.2.2-20260417
ARG SEMERU_JRE_VERSION=26.0.2.10
""",
        encoding="utf-8",
    )

    def tags(url: str) -> list[str]:
        return {
            "https://github.com/freerouting/freerouting": ["v2.3.0"],
            "https://github.com/astral-sh/uv": ["0.12.7"],
            "https://github.com/espressif/esp-idf": ["v6.1"],
            "https://github.com/espressif/qemu": [
                "esp-develop-9.2.2-20260417",
                "esp-develop-9.2.2-20260418",
            ],
            "https://github.com/ibmruntimes/semeru26-binaries": ["jdk-26.0.2.10"],
        }[url]

    statuses = check_docker_args(tmp_path, list_remote_tags=tags)
    qemu = next(status for status in statuses if status.name == "QEMU_ESP_TAG")
    assert qemu.latest.endswith("20260418")
    assert qemu.outdated


def test_submodule_pin_mismatch_is_reported(tmp_path: Path) -> None:
    _write_repo(
        tmp_path,
        pyproject='[project]\ndependencies = ["openhands-sdk==1.0.0"]\n',
        lock="",
    )
    (tmp_path / ".gitmodules").write_text(
        '[submodule "vendor/software-agent-sdk"]\n'
        "\tpath = vendor/software-agent-sdk\n"
        "\turl = https://github.com/OpenHands/software-agent-sdk\n",
        encoding="utf-8",
    )

    def run_git(command: list[str], _cwd: Path) -> str:
        if "config" in command:
            return "https://github.com/OpenHands/software-agent-sdk"
        if "describe" in command:
            return "v1.44.1"
        raise AssertionError(command)

    statuses = check_submodule(
        tmp_path,
        list_remote_tags=lambda _url: ["v1.44.1", "v1.45.0"],
        run_git=run_git,
    )
    pin = next(status for status in statuses if status.name == "openhands-sdk pin")
    assert pin.outdated
    assert pin.current == "1.0.0"
    assert pin.latest == "1.44.1"


def test_pypi_missing_lock_entry_fails_closed(tmp_path: Path) -> None:
    root = _write_repo(
        tmp_path,
        pyproject='[project]\ndependencies = ["missing-package"]\n',
        lock='[[package]]\nname = "other-package"\nversion = "1.0.0"\n',
    )
    with pytest.raises(ValueError, match="no resolved version"):
        check_pypi(root, fetch_json=lambda _url: {"info": {"version": "1.0"}})


def test_markdown_no_updates() -> None:
    markdown = render_markdown(
        [DependencyStatus("pypi", "pytest", "9.0.0", "9.0.0", "pyproject.toml", False)]
    )
    assert "更新候補はありません。" in markdown
    assert markdown.count("| 依存 | 現在 | 最新 | 参照 |") == 4
    assert "更新候補: 0件" not in markdown
