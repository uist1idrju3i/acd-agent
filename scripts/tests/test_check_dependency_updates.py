"""Tests for dependency update checks."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts.check_dependency_updates import (
    DependencyStatus,
    check_docker_args,
    check_docker_base,
    check_git_pin,
    check_github_actions,
    check_github_release_downloads,
    check_pypi,
    check_pypi_lock,
    check_python_versions,
    check_semeru_majors,
    check_submodule,
    check_tool_upstream,
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
        pyproject=(
            "[project]\ndependencies = ["
            '"openhands-sdk==1.0.0", "openhands-tools==1.0.0", '
            '"openhands-workspace==1.0.0"]\n'
        ),
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
    assert {status.name for status in statuses} == {
        "software-agent-sdk",
        "openhands-sdk pin",
        "openhands-tools pin",
        "openhands-workspace pin",
    }


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
    assert markdown.count("| 依存 | 現在 | 最新 | 参照 |") == 10
    assert "更新候補: 0件" not in markdown


def test_pypi_lock_parses_changes_and_excludes_direct_dependencies(tmp_path: Path) -> None:
    root = _write_repo(
        tmp_path,
        pyproject='[project]\ndependencies = ["direct-package>=1"]\n',
        lock='[[package]]\nname = "direct-package"\nversion = "1.0.0"\n',
    )
    calls: list[tuple[list[str], Path]] = []

    def run_uv(command: list[str], cwd: Path) -> str:
        calls.append((command, cwd))
        return """\
INFO uv 0.1
Update direct-package v1.0.0 -> v1.1.0
Update transitive-package v2.0.0 -> v2.1.0
Add boto3 v1.43.89
Remove old-package v0.9.0
WARN ignored
"""

    statuses = check_pypi_lock(root, {"direct-package"}, run_uv=run_uv)
    assert calls == [(["uv", "lock", "--upgrade", "--dry-run"], root)]
    assert [(status.name, status.current, status.latest, status.note) for status in statuses] == [
        ("transitive-package", "2.0.0", "2.1.0", ""),
        ("boto3", "-", "1.43.89", "would be added"),
        ("old-package", "0.9.0", "-", "would be removed"),
    ]


def test_docker_base_paginates_and_uses_only_yy_mm_tags(tmp_path: Path) -> None:
    docker = tmp_path / "docker"
    docker.mkdir()
    (docker / "acd-tools.Dockerfile").write_text("FROM ubuntu:26.04\n", encoding="utf-8")
    responses = {
        "https://hub.docker.com/v2/repositories/library/ubuntu/tags?page_size=100": {
            "results": [{"name": "26.04"}, {"name": "latest"}],
            "next": "https://example.invalid/page2",
        },
        "https://example.invalid/page2": {
            "results": [{"name": "25.10"}, {"name": "26.99.0"}],
            "next": None,
        },
    }
    statuses = check_docker_base(tmp_path, fetch_json=responses.__getitem__)
    assert statuses == [
        DependencyStatus(
            "docker-base", "ubuntu", "26.04", "26.04", "docker/acd-tools.Dockerfile", False
        )
    ]


def test_tool_upstream_excludes_kicad_development_and_parses_ngspice(tmp_path: Path) -> None:
    tools = {
        "kicad-cli": "10.0.6",
        "ngspice": "45.2",
        "cmake": "cmake version 4.2.3",
        "ninja": "1.13.2",
        "ccache": "ccache version 4.12.3",
        "git": "git version 2.53.0",
        "python3.14": "Python 3.14.4",
    }
    (tmp_path / "docker").mkdir()
    (tmp_path / "docker" / "image-digests.json").write_text(
        json.dumps({"acd_tools": {"tools": tools}}), encoding="utf-8"
    )
    tags = {
        "https://github.com/KiCad/kicad-source-mirror": ["10.99.0", "10.0.6"],
        "https://github.com/Kitware/CMake": ["v4.2.3"],
        "https://github.com/ninja-build/ninja": ["v1.13.2"],
        "https://github.com/ccache/ccache": ["v4.12.3"],
        "https://github.com/git/git": ["v2.53.0"],
        "https://github.com/python/cpython": ["v3.14.4", "v3.14.5", "v3.15.0"],
    }

    def list_tags(url: str) -> list[str]:
        return tags[url]

    def fetch(url: str) -> object:
        assert url.endswith("best_release.json")
        return {"release": {"filename": "/ng-spice-rework/47/ngspice-47_64.7z"}}

    statuses = check_tool_upstream(
        tmp_path,
        fetch_json=fetch,
        list_remote_tags=list_tags,
    )
    by_name = {status.name: status for status in statuses}
    assert by_name["kicad-cli"].latest == "10.0.6"
    assert by_name["ngspice"].latest == "47"
    assert by_name["python3.14"].latest == "3.14.5"
    assert by_name["python (minor series)"].latest == "3.15"


def test_semeru_newer_major_paginates_until_empty(tmp_path: Path) -> None:
    docker = tmp_path / "docker"
    docker.mkdir()
    (docker / "acd-tools.Dockerfile").write_text(
        "ARG SEMERU_JRE_VERSION=26.0.2.10\n", encoding="utf-8"
    )
    calls: list[str] = []
    pages = {
        1: [{"name": "semeru26-binaries"}, {"name": "semeru27-binaries"}],
        2: [],
    }

    def fetch(url: str) -> object:
        calls.append(url)
        return pages[int(url.rsplit("page=", 1)[1])]

    statuses = check_semeru_majors(tmp_path, fetch_json=fetch)
    assert calls[-1].endswith("page=2")
    assert statuses[0].latest == "27"
    assert "semeru27-binaries" in statuses[0].note


def test_release_download_parsing(tmp_path: Path) -> None:
    workflow = tmp_path / ".github" / "workflows"
    workflow.mkdir(parents=True)
    (workflow / "test.yml").write_text(
        "run: curl -L https://github.com/rhysd/actionlint/releases/download/v1.7.7/actionlint.tar.gz\n",
        encoding="utf-8",
    )
    statuses = check_github_release_downloads(
        tmp_path,
        list_remote_tags=lambda url: (
            ["v1.7.7", "v1.8.0"] if url.endswith("rhysd/actionlint") else []
        ),
    )
    assert statuses[0].surface == "github-release-download"
    assert statuses[0].outdated


def test_git_pin_mismatch(tmp_path: Path) -> None:
    libraries = tmp_path / "libraries"
    libraries.mkdir()
    current = "a" * 40
    latest = "b" * 40
    (libraries / "README.md").write_text(
        f"""\
- 取得元URL: `https://github.com/espressif/kicad-libraries`
- 取得commit: `{current}`
""",
        encoding="utf-8",
    )
    status = check_git_pin(
        tmp_path,
        list_remote_head=lambda url: latest,
    )[0]
    assert status.outdated
    assert status.latest == latest[:12]


def test_python_version_checks_minor_series(tmp_path: Path) -> None:
    workflow = tmp_path / ".github" / "workflows"
    workflow.mkdir(parents=True)
    (workflow / "test.yml").write_text('python-version: "3.12"\n', encoding="utf-8")
    docker = tmp_path / "docker"
    docker.mkdir()
    (docker / "acd-tools.Dockerfile").write_text(
        "ARG ESP_IDF_PYTHON_VERSION=3.12\n", encoding="utf-8"
    )
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nrequires-python = ">=3.12"\n', encoding="utf-8"
    )
    statuses = check_python_versions(
        tmp_path,
        list_remote_tags=lambda _url: ["v3.12.4", "v3.13.0"],
    )
    assert len(statuses) == 3
    assert all(status.outdated for status in statuses)
