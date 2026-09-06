"""Tests for dependency update checks."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
from scripts.check_dependency_updates import (
    DependencyDeferral,
    DependencyStatus,
    apply_deferrals,
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
    load_deferrals,
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
ARG FREEROUTING_VERSION=2.4.1
ARG UV_VERSION=0.12.10
ARG ESP_IDF_VERSION=v6.1
ARG QEMU_ESP_TAG=esp-develop-9.2.2-20260417
ARG SEMERU_JRE_VERSION=26.0.2.10
""",
        encoding="utf-8",
    )

    def tags(url: str) -> list[str]:
        return {
            "https://github.com/freerouting/freerouting": ["v2.4.1"],
            "https://github.com/astral-sh/uv": ["0.12.10"],
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
    assert markdown.count("| 依存 | 現在 | 最新 | 状態 | 参照 |") == 1
    assert "| pytest | 9.0.0 | 9.0.0 | 最新 | pyproject.toml |" in markdown
    assert "## PyPI（uv.lock間接依存）\n\n間接依存はdriftのある項目のみ表示" in markdown
    assert "## submodule\n\n確認対象なし" in markdown
    assert "更新候補: 0件" not in markdown


def test_markdown_lists_outdated_before_current_items() -> None:
    markdown = render_markdown(
        [
            DependencyStatus("pypi", "current-package", "1.0.0", "1.0.0", "pyproject.toml", False),
            DependencyStatus("pypi", "outdated-package", "1.0.0", "2.0.0", "pyproject.toml", True),
        ]
    )
    outdated_row = "| outdated-package | 1.0.0 | 2.0.0 | 更新あり | pyproject.toml |"
    current_row = "| current-package | 1.0.0 | 1.0.0 | 最新 | pyproject.toml |"
    assert outdated_row in markdown
    assert current_row in markdown
    assert markdown.index(outdated_row) < markdown.index(current_row)


def test_markdown_renders_deferred_rows_before_current_rows() -> None:
    markdown = render_markdown(
        [
            DependencyStatus("pypi", "current", "1.0.0", "1.0.0", "pyproject.toml", False),
            DependencyStatus(
                "pypi",
                "deferred",
                "1.0.0",
                "2.0.0",
                "pyproject.toml",
                False,
                "deferred until 2026-12-01: compatibility",
                True,
            ),
            DependencyStatus("pypi", "outdated", "1.0.0", "3.0.0", "pyproject.toml", True),
        ]
    )
    deferred_row = "| deferred | 1.0.0 | "
    deferred_row += "2.0.0 (deferred until 2026-12-01: compatibility) | 保留 |"
    assert deferred_row in markdown
    assert "保留: 1件（scripts/dependency_update_deferrals.json、期限到来で再候補化）" in markdown
    assert markdown.index("| outdated |") < markdown.index("| deferred |")
    assert markdown.index("| deferred |") < markdown.index("| current |")


def test_deferrals_apply_exact_and_wildcard_matches_but_not_changed_or_expired() -> None:
    statuses = apply_deferrals(
        [
            DependencyStatus(
                "pypi",
                "cadquery-ocp",
                "7.9.3",
                "8.0.1.0.0",
                "pyproject.toml",
                True,
                "compatibility",
            ),
            DependencyStatus(
                "python-version", "Python version (ci.yml)", "3.12", "3.14", "ci.yml", True
            ),
            DependencyStatus("pypi", "changed", "1.0.0", "2.0.0", "pyproject.toml", True),
            DependencyStatus("pypi", "expired", "1.0.0", "2.0.0", "pyproject.toml", True),
        ],
        [
            DependencyDeferral(
                "pypi",
                "cadquery-ocp",
                "8.0.1.0.0",
                date(2026, 12, 1),
                "blocked",
            ),
            DependencyDeferral(
                "python-version",
                "*",
                "3.14",
                date(2026, 12, 1),
                "validation required",
            ),
            DependencyDeferral(
                "pypi",
                "changed",
                "2.0.1",
                date(2026, 12, 1),
                "old version only",
            ),
            DependencyDeferral(
                "pypi",
                "expired",
                "2.0.0",
                date(2026, 1, 1),
                "期限切れ",
            ),
        ],
        date(2026, 9, 6),
    )
    assert statuses[0].deferred
    assert not statuses[0].outdated
    assert statuses[0].note == "compatibility; deferred until 2026-12-01: blocked"
    assert statuses[1].deferred
    assert statuses[2].outdated
    assert statuses[3].outdated


def test_load_deferrals_rejects_malformed_file(tmp_path: Path) -> None:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "dependency_update_deferrals.json").write_text(
        '{"deferrals": [{"surface": "unknown", "name": "*", "latest": "1", '
        '"review_by": "2026-12-01", "reason": "invalid", "extra": true}]}',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unknown or missing keys"):
        load_deferrals(tmp_path)


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
            "results": [{"name": "25.10"}, {"name": "26.10"}, {"name": "26.99.0"}],
            "next": None,
        },
    }
    statuses = check_docker_base(tmp_path, fetch_json=responses.__getitem__)
    assert statuses == [
        DependencyStatus(
            "docker-base", "ubuntu", "26.04", "26.04", "docker/acd-tools.Dockerfile", False
        )
    ]


def test_docker_base_reports_newer_lts(tmp_path: Path) -> None:
    docker = tmp_path / "docker"
    docker.mkdir()
    (docker / "acd-tools.Dockerfile").write_text("FROM ubuntu:26.04\n", encoding="utf-8")
    responses = {
        "https://hub.docker.com/v2/repositories/library/ubuntu/tags?page_size=100": {
            "results": [{"name": "26.10"}, {"name": "28.04"}],
            "next": None,
        },
    }

    statuses = check_docker_base(tmp_path, fetch_json=responses.__getitem__)

    assert statuses[0].latest == "28.04"
    assert statuses[0].outdated is True


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
    (tmp_path / "docker" / "acd-tools.Dockerfile").write_text(
        "FROM ubuntu:26.04\n", encoding="utf-8"
    )
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
        if url.endswith("best_release.json"):
            return {"release": {"filename": "/ng-spice-rework/47/ngspice-47_64.7z"}}
        if url == "https://api.launchpad.net/1.0/ubuntu/series":
            return {"entries": [{"version": "26.04", "name": "resolute"}]}
        package = url.split("binary_name=", 1)[1].split("&", 1)[0]
        versions = {
            "ngspice": "45.2+ds-1",
            "cmake": "4.2.3-2ubuntu2",
            "ninja-build": "1.13.2-1",
            "ccache": "4.12.3-1",
            "git": "1:2.53.0-1ubuntu1",
            "python3.14": "3.14.4-1ubuntu0.1",
        }
        return {"entries": [{"binary_package_version": versions[package]}]}

    statuses = check_tool_upstream(
        tmp_path,
        fetch_json=fetch,
        list_remote_tags=list_tags,
    )
    by_name = {status.name: status for status in statuses}
    assert by_name["kicad-cli"].latest == "10.0.6"
    assert by_name["ngspice"].latest == "45.2"
    assert not by_name["ngspice"].outdated
    assert by_name["ngspice"].note == "apt ubuntu:26.04; upstream 47"
    assert by_name["git"].latest == "2.53.0"
    assert by_name["python3.14"].latest == "3.14.4"
    assert by_name["python3.14"].note == "apt ubuntu:26.04; upstream 3.14.5"
    assert by_name["python (minor series)"].latest == "3.15"


def test_tool_upstream_reports_newer_apt_archive_version(tmp_path: Path) -> None:
    tools = {
        "kicad-cli": "10.0.6",
        "ngspice": "45.2",
        "cmake": "4.2.3",
        "ninja": "1.13.2",
        "ccache": "4.12.3",
        "git": "2.53.0",
        "python3.14": "3.14.4",
    }
    docker = tmp_path / "docker"
    docker.mkdir()
    (docker / "acd-tools.Dockerfile").write_text("FROM ubuntu:26.04\n", encoding="utf-8")
    (docker / "image-digests.json").write_text(
        json.dumps({"acd_tools": {"tools": tools}}), encoding="utf-8"
    )

    def tags(url: str) -> list[str]:
        if url.endswith("KiCad/kicad-source-mirror"):
            return ["10.0.6"]
        if url.endswith("python/cpython"):
            return ["v3.14.4"]
        return ["v4.2.3", "v1.13.2", "v4.12.3", "v2.53.0"]

    def fetch(url: str) -> object:
        if url.endswith("best_release.json"):
            return {"release": {"filename": "/ng-spice-rework/47/ngspice-47_64.7z"}}
        if url.endswith("/series"):
            return {"entries": [{"version": "26.04", "name": "resolute"}]}
        package = url.split("binary_name=", 1)[1].split("&", 1)[0]
        versions = {
            "ngspice": "47.0+ds-1",
            "cmake": "4.2.3-2ubuntu2",
            "ninja-build": "1.13.2-1",
            "ccache": "4.12.3-1",
            "git": "1:2.53.0-1ubuntu1",
            "python3.14": "3.14.4-1ubuntu0.1",
        }
        return {"entries": [{"binary_package_version": versions[package]}]}

    statuses = check_tool_upstream(tmp_path, fetch_json=fetch, list_remote_tags=tags)
    ngspice = next(status for status in statuses if status.name == "ngspice")
    assert ngspice.latest == "47.0"
    assert ngspice.outdated
    assert ngspice.note == "apt ubuntu:26.04; upstream 47"


def test_tool_upstream_fails_when_ubuntu_series_is_missing(tmp_path: Path) -> None:
    docker = tmp_path / "docker"
    docker.mkdir()
    (docker / "acd-tools.Dockerfile").write_text("FROM ubuntu:26.04\n", encoding="utf-8")
    (docker / "image-digests.json").write_text(
        json.dumps(
            {
                "acd_tools": {
                    "tools": {
                        "kicad-cli": "10.0.6",
                        "ngspice": "45.2",
                        "cmake": "4.2.3",
                        "ninja": "1.13.2",
                        "ccache": "4.12.3",
                        "git": "2.53.0",
                        "python3.14": "3.14.4",
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    def fetch(url: str) -> object:
        if url.endswith("best_release.json"):
            return {"release": {"filename": "/ng-spice-rework/47/ngspice-47_64.7z"}}
        if url.endswith("/series"):
            return {"entries": [{"version": "25.04", "name": "questing"}]}
        raise AssertionError(url)

    with pytest.raises(ValueError, match="Ubuntu series was not found"):
        check_tool_upstream(
            tmp_path,
            fetch_json=fetch,
            list_remote_tags=lambda url: (
                ["10.0.6"]
                if url.endswith("KiCad/kicad-source-mirror")
                else ["v3.14.4"]
                if url.endswith("python/cpython")
                else ["v4.2.3", "v1.13.2", "v4.12.3", "v2.53.0"]
            ),
        )


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
        if "/releases?" in url:
            return [{"prerelease": False, "draft": False}]
        return pages[int(url.rsplit("page=", 1)[1])]

    statuses = check_semeru_majors(tmp_path, fetch_json=fetch)
    assert any(call.endswith("page=2") for call in calls)
    assert statuses[0].latest == "27"
    assert "semeru27-binaries" in statuses[0].note


def test_semeru_prerelease_only_major_is_not_outdated(tmp_path: Path) -> None:
    docker = tmp_path / "docker"
    docker.mkdir()
    (docker / "acd-tools.Dockerfile").write_text(
        "ARG SEMERU_JRE_VERSION=26.0.2.10\n", encoding="utf-8"
    )

    def fetch(url: str) -> object:
        if url.endswith("page=1"):
            return [{"name": "semeru27-binaries"}]
        if url.endswith("page=2"):
            return []
        if "/releases?" in url:
            return [{"prerelease": True, "draft": False}]
        raise AssertionError(url)

    statuses = check_semeru_majors(tmp_path, fetch_json=fetch)

    assert statuses == [
        DependencyStatus(
            "docker-arg",
            "SEMERU_JRE_VERSION (major)",
            "26",
            "27",
            "docker/acd-tools.Dockerfile",
            False,
            "27 is prerelease only",
        )
    ]


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


def test_git_pins_support_multiple_sources(tmp_path: Path) -> None:
    libraries = tmp_path / "libraries"
    libraries.mkdir()
    espressif = "a" * 40
    cern = "c" * 40
    latest_espressif = "b" * 40
    latest_cern = "d" * 40
    (libraries / "README.md").write_text(
        f"""\
## Espressif
- 取得元URL: `https://github.com/espressif/kicad-libraries`
- 取得commit: `{espressif}`
## CERN
- 取得元URL: `https://gitlab.com/ohwr/cern-kicad-libs`
- 取得commit: `{cern}`
""",
        encoding="utf-8",
    )
    latest = {
        "https://github.com/espressif/kicad-libraries": latest_espressif,
        "https://gitlab.com/ohwr/cern-kicad-libs": latest_cern,
    }
    calls: list[str] = []
    statuses = check_git_pin(
        tmp_path,
        list_remote_head=lambda url: calls.append(url) or latest[url],
    )
    assert [status.name for status in statuses] == [
        "espressif/kicad-libraries",
        "ohwr/cern-kicad-libs",
    ]
    assert calls == list(latest)


def test_git_pin_missing_commit_fails_closed(tmp_path: Path) -> None:
    libraries = tmp_path / "libraries"
    libraries.mkdir()
    (libraries / "README.md").write_text(
        "- 取得元URL: `https://gitlab.com/ohwr/cern-kicad-libs`\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="mismatched URL"):
        check_git_pin(tmp_path, list_remote_head=lambda _url: "a" * 40)


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
