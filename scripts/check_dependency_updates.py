#!/usr/bin/env python3
"""Check dependency versions without modifying repository files."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tomllib
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, cast
from urllib.request import Request, urlopen

FetchJson = Callable[[str], dict[str, Any]]
ListRemoteTags = Callable[[str], list[str]]
RunGit = Callable[[list[str], Path], str]

PACKAGE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*")
ACTION_RE = re.compile(
    r"uses:\s*([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)(?:/[^@\s]+)?@(\S+)"
    r"(?:\s*#\s*(v?\d[\w.-]*))?"
)
DOCKER_ARG_RE = re.compile(r"^\s*ARG\s+([A-Za-z_][A-Za-z0-9_]*)=(\S+)\s*$", re.MULTILINE)
STABLE_TAG_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
ACTION_TAG_RE = re.compile(r"^v?(\d+)(?:\.(\d+))?(?:\.(\d+))?$")


@dataclass(frozen=True)
class DependencyStatus:
    surface: str
    name: str
    current: str
    latest: str
    source: str
    outdated: bool
    note: str = ""


@dataclass(frozen=True)
class DockerArgSpec:
    arg: str
    repo: str
    tag_pattern: str


DOCKER_ARG_SPECS = (
    DockerArgSpec("FREEROUTING_VERSION", "freerouting/freerouting", r"^v(\d+)\.(\d+)\.(\d+)$"),
    DockerArgSpec("UV_VERSION", "astral-sh/uv", r"^(\d+)\.(\d+)\.(\d+)$"),
    DockerArgSpec(
        "ESP_IDF_VERSION",
        "espressif/esp-idf",
        r"^v(\d+)\.(\d+)(?:\.(\d+))?$",
    ),
    DockerArgSpec(
        "QEMU_ESP_TAG",
        "espressif/qemu",
        r"^esp-develop-(\d+)\.(\d+)\.(\d+)-(\d{8})$",
    ),
    DockerArgSpec(
        "SEMERU_JRE_VERSION",
        "ibmruntimes/semeru{major}-binaries",
        r"^jdk-(\d+)\.(\d+)\.(\d+)\.(\d+)$",
    ),
)


def _default_fetch_json(url: str) -> dict[str, Any]:
    request = Request(url, headers={"Accept": "application/json"})
    with urlopen(request, timeout=20) as response:
        payload: Any = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON response is not an object: {url}")
    return cast(dict[str, Any], payload)


def _default_list_remote_tags(url: str) -> list[str]:
    result = subprocess.run(
        ["git", "ls-remote", "--tags", url],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=20,
    )
    tags: list[str] = []
    for line in result.stdout.splitlines():
        ref = line.split(maxsplit=1)
        if len(ref) != 2 or ref[1].endswith("^{}"):
            continue
        prefix = "refs/tags/"
        if ref[1].startswith(prefix):
            tags.append(ref[1][len(prefix) :])
    return tags


def _default_run_git(command: list[str], cwd: Path) -> str:
    result = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=cwd,
        timeout=20,
    )
    return result.stdout.strip()


def normalize_name(name: str) -> str:
    """Normalize a Python distribution name according to PEP 503."""
    return re.sub(r"[-_.]+", "-", name.lower())


def _package_name(requirement: str) -> str:
    match = PACKAGE_NAME_RE.match(requirement.strip())
    if match is None:
        raise ValueError(f"cannot parse dependency name: {requirement!r}")
    return normalize_name(match.group(0))


def _project_data(repo_root: Path) -> dict[str, Any]:
    path = repo_root / "pyproject.toml"
    with path.open("rb") as stream:
        payload: Any = tomllib.load(stream)
    if not isinstance(payload, dict):
        raise ValueError("pyproject.toml is not an object")
    return cast(dict[str, Any], payload)


def _dict(value: Any, message: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(message)
    return cast(dict[str, Any], value)


def _dependency_names(data: dict[str, Any]) -> list[str]:
    project = _dict(data.get("project"), "pyproject.toml has no [project] table")
    raw_dependencies: list[str] = []
    dependencies = project.get("dependencies")
    if not isinstance(dependencies, list):
        raise ValueError("[project].dependencies is not an array")
    dependencies = cast(list[Any], dependencies)
    if not all(isinstance(dependency, str) for dependency in dependencies):
        raise ValueError("[project].dependencies contains a non-string entry")
    raw_dependencies.extend(cast(str, dependency) for dependency in dependencies)
    groups = data.get("dependency-groups", {})
    groups = _dict(groups, "[dependency-groups] is not a table")
    for group_name, group in groups.items():
        if not isinstance(group, list):
            raise ValueError(f"[dependency-groups].{group_name} is not an array")
        group = cast(list[Any], group)
        if not all(isinstance(dependency, str) for dependency in group):
            raise ValueError(f"[dependency-groups].{group_name} contains a non-string entry")
        raw_dependencies.extend(cast(str, dependency) for dependency in group)
    names: list[str] = []
    for requirement in raw_dependencies:
        name = _package_name(requirement)
        if name not in names:
            names.append(name)
    return names


def _uv_source_names(data: dict[str, Any]) -> set[str]:
    tool = _dict(data.get("tool", {}), "[tool] is not a table")
    uv = _dict(tool.get("uv", {}), "[tool.uv] is not a table")
    sources = _dict(uv.get("sources", {}), "[tool.uv.sources] is not a table")
    return {normalize_name(name) for name in sources}


def _lock_versions(repo_root: Path) -> dict[str, str]:
    path = repo_root / "uv.lock"
    with path.open("rb") as stream:
        payload: Any = tomllib.load(stream)
    lock_data = _dict(payload, "uv.lock is not an object")
    packages = lock_data.get("package")
    if not isinstance(packages, list):
        raise ValueError("uv.lock has no [[package]] entries")
    packages = cast(list[Any], packages)
    versions: dict[str, str] = {}
    for package in packages:
        if not isinstance(package, dict):
            raise ValueError("uv.lock contains a malformed package entry")
        package_data = _dict(package, "uv.lock contains a malformed package entry")
        name = package_data.get("name")
        version = package_data.get("version")
        if isinstance(name, str) and isinstance(version, str):
            versions[normalize_name(name)] = version
    return versions


def check_pypi(
    repo_root: Path,
    *,
    fetch_json: FetchJson = _default_fetch_json,
) -> list[DependencyStatus]:
    data = _project_data(repo_root)
    source_names = _uv_source_names(data)
    versions = _lock_versions(repo_root)
    statuses: list[DependencyStatus] = []
    for name in _dependency_names(data):
        if name in source_names:
            continue
        current = versions.get(name)
        if current is None:
            raise ValueError(f"uv.lock has no resolved version for {name}")
        payload = fetch_json(f"https://pypi.org/pypi/{name}/json")
        info = _dict(payload.get("info"), f"PyPI response has no info for {name}")
        latest = info.get("version")
        if not isinstance(latest, str) or not latest:
            raise ValueError(f"PyPI response has no version for {name}")
        statuses.append(
            DependencyStatus(
                surface="pypi",
                name=name,
                current=current,
                latest=latest,
                source="pyproject.toml",
                outdated=latest != current,
            )
        )
    return statuses


def _highest_stable_tag(tags: list[str], pattern: re.Pattern[str]) -> tuple[str, tuple[int, ...]]:
    candidates: list[tuple[tuple[int, ...], str]] = []
    for tag in tags:
        match = pattern.fullmatch(tag)
        if match is None:
            continue
        values = tuple(int(group or "0") for group in match.groups())
        candidates.append((values, tag))
    if not candidates:
        raise ValueError("no stable remote tags matched the expected pattern")
    values, tag = max(candidates)
    return tag, values


def _gitmodules_url(repo_root: Path, run_git: RunGit) -> str:
    return run_git(
        [
            "git",
            "config",
            "--file",
            ".gitmodules",
            "--get",
            "submodule.vendor/software-agent-sdk.url",
        ],
        repo_root,
    )


def _sdk_pin(data: dict[str, Any]) -> str | None:
    project = _dict(data.get("project"), "pyproject.toml has no [project] table")
    dependencies = project.get("dependencies")
    if not isinstance(dependencies, list):
        raise ValueError("[project].dependencies is not an array")
    dependencies = cast(list[Any], dependencies)
    for requirement in dependencies:
        if (
            isinstance(requirement, str)
            and normalize_name(_package_name(requirement)) == "openhands-sdk"
        ):
            match = re.search(r"==\s*([A-Za-z0-9][A-Za-z0-9._-]*)", requirement)
            if match is None:
                raise ValueError("openhands-sdk must have an exact pin")
            return match.group(1)
    raise ValueError("pyproject.toml has no openhands-sdk dependency")


def check_submodule(
    repo_root: Path,
    *,
    list_remote_tags: ListRemoteTags = _default_list_remote_tags,
    run_git: RunGit = _default_run_git,
) -> list[DependencyStatus]:
    url = _gitmodules_url(repo_root, run_git)
    submodule_path = repo_root / "vendor" / "software-agent-sdk"
    note = ""
    try:
        current = run_git(
            [
                "git",
                "-C",
                str(submodule_path),
                "describe",
                "--tags",
                "--exact-match",
                "HEAD",
            ],
            repo_root,
        )
    except (OSError, subprocess.CalledProcessError, ValueError):
        current = run_git(["git", "-C", str(submodule_path), "rev-parse", "HEAD"], repo_root)
        note = "HEAD is not on a tag"
    latest, _ = _highest_stable_tag(list_remote_tags(url), STABLE_TAG_RE)
    statuses = [
        DependencyStatus(
            surface="submodule",
            name="software-agent-sdk",
            current=current,
            latest=latest,
            source=".gitmodules",
            outdated=current != latest or bool(note),
            note=note,
        )
    ]
    pin = _sdk_pin(_project_data(repo_root))
    if pin is None:
        raise ValueError("pyproject.toml has no openhands-sdk pin")
    submodule_pin = current.removeprefix("v") if STABLE_TAG_RE.fullmatch(current) else None
    if submodule_pin is not None and pin != submodule_pin:
        statuses.append(
            DependencyStatus(
                surface="submodule",
                name="openhands-sdk pin",
                current=pin,
                latest=submodule_pin,
                source="pyproject.toml",
                outdated=True,
                note="pyproject.toml pin and submodule tag must stay in sync",
            )
        )
    return statuses


def _numeric_version(value: str) -> tuple[int, ...]:
    match = ACTION_TAG_RE.fullmatch(value)
    if match is None:
        raise ValueError(f"not a numeric version: {value}")
    return tuple(int(group or "0") for group in match.groups() if group is not None)


def _version_outdated(current: tuple[int, ...], latest: tuple[int, ...]) -> bool:
    return tuple(latest[: len(current)]) != current


def check_github_actions(
    repo_root: Path,
    *,
    list_remote_tags: ListRemoteTags = _default_list_remote_tags,
) -> list[DependencyStatus]:
    found: dict[tuple[str, str], tuple[str, str, str]] = {}
    workflows = sorted((repo_root / ".github" / "workflows").glob("*.yml"))
    for workflow in workflows:
        for line in workflow.read_text(encoding="utf-8").splitlines():
            match = ACTION_RE.search(line)
            if match is None:
                continue
            repo, ref, comment_version = match.groups()
            if repo.startswith("./") or repo.startswith("docker://"):
                continue
            key = (repo, ref)
            source = str(workflow.relative_to(repo_root))
            if key in found:
                old_repo, old_ref, old_sources = found[key]
                found[key] = (old_repo, old_ref, f"{old_sources}, {source}")
            else:
                found[key] = (repo, comment_version or ref, source)
    statuses: list[DependencyStatus] = []
    for (repo, _ref), (_, current, source) in found.items():
        latest, latest_values = _highest_stable_tag(
            list_remote_tags(f"https://github.com/{repo}"),
            ACTION_TAG_RE,
        )
        current_values = _numeric_version(current)
        statuses.append(
            DependencyStatus(
                surface="github-actions",
                name=repo,
                current=current,
                latest=latest,
                source=source,
                outdated=_version_outdated(current_values, latest_values),
            )
        )
    return statuses


def check_docker_args(
    repo_root: Path,
    *,
    list_remote_tags: ListRemoteTags = _default_list_remote_tags,
) -> list[DependencyStatus]:
    path = repo_root / "docker" / "acd-tools.Dockerfile"
    values = {
        name: value for name, value in DOCKER_ARG_RE.findall(path.read_text(encoding="utf-8"))
    }
    statuses: list[DependencyStatus] = []
    for spec in DOCKER_ARG_SPECS:
        current = values.get(spec.arg)
        if current is None:
            raise ValueError(f"Dockerfile is missing required ARG {spec.arg}")
        pattern = re.compile(spec.tag_pattern)
        if spec.arg == "SEMERU_JRE_VERSION":
            current_for_match = f"jdk-{current}"
        elif spec.arg in {"FREEROUTING_VERSION", "ESP_IDF_VERSION"} and not current.startswith("v"):
            current_for_match = f"v{current}"
        else:
            current_for_match = current
        current_match = pattern.fullmatch(current_for_match)
        if current_match is None:
            raise ValueError(f"Docker ARG {spec.arg} has invalid value: {current}")
        current_values = tuple(int(group or "0") for group in current_match.groups())
        repo = spec.repo
        if "{major}" in repo:
            repo = repo.format(major=current_values[0])
        latest, latest_values = _highest_stable_tag(
            list_remote_tags(f"https://github.com/{repo}"),
            pattern,
        )
        statuses.append(
            DependencyStatus(
                surface="docker-arg",
                name=spec.arg,
                current=current,
                latest=latest,
                source="docker/acd-tools.Dockerfile",
                outdated=latest_values > current_values,
            )
        )
    return statuses


def check_dependency_updates(
    repo_root: Path,
    *,
    fetch_json: FetchJson = _default_fetch_json,
    list_remote_tags: ListRemoteTags = _default_list_remote_tags,
    run_git: RunGit = _default_run_git,
) -> list[DependencyStatus]:
    return [
        *check_pypi(repo_root, fetch_json=fetch_json),
        *check_submodule(repo_root, list_remote_tags=list_remote_tags, run_git=run_git),
        *check_github_actions(repo_root, list_remote_tags=list_remote_tags),
        *check_docker_args(repo_root, list_remote_tags=list_remote_tags),
    ]


def render_markdown(statuses: list[DependencyStatus]) -> str:
    labels = {
        "pypi": "PyPI",
        "submodule": "submodule",
        "github-actions": "GitHub Actions",
        "docker-arg": "Docker ARG",
    }
    lines = ["# 依存アップデート確認レポート", ""]
    for surface in ("pypi", "submodule", "github-actions", "docker-arg"):
        lines.extend(
            [
                f"## {labels[surface]}",
                "",
                "| 依存 | 現在 | 最新 | 参照 |",
                "| --- | --- | --- | --- |",
            ]
        )
        rows = [status for status in statuses if status.surface == surface and status.outdated]
        if rows:
            for status in rows:
                latest = status.latest
                if status.note:
                    latest = f"{latest} ({status.note})"
                lines.append(f"| {status.name} | {status.current} | {latest} | {status.source} |")
        lines.append("")
    outdated_count = sum(status.outdated for status in statuses)
    lines.append(f"更新候補: {outdated_count}件" if outdated_count else "更新候補はありません。")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--markdown", type=Path)
    parser.add_argument("--json", dest="json_path", type=Path)
    args = parser.parse_args(argv)
    try:
        statuses = check_dependency_updates(args.repo_root.resolve())
        markdown = render_markdown(statuses)
        if args.markdown is not None:
            args.markdown.write_text(markdown, encoding="utf-8")
        if args.json_path is not None:
            payload = {
                "statuses": [asdict(status) for status in statuses],
                "outdated_count": sum(status.outdated for status in statuses),
            }
            args.json_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        print(markdown, end="")
        return 0
    except (OSError, ValueError, subprocess.CalledProcessError, tomllib.TOMLDecodeError) as exc:
        print(f"依存更新確認に失敗しました: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
