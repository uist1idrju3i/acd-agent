#!/usr/bin/env python3
"""Check dependency versions without modifying repository files."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tomllib
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

FetchJson = Callable[[str], Any]
ListRemoteTags = Callable[[str], list[str]]
ListRemoteHead = Callable[[str], str]
RunGit = Callable[[list[str], Path], str]
RunUv = Callable[[list[str], Path], str]
ExcludeTag = Callable[[str, tuple[int, ...]], bool]

PACKAGE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*")
ACTION_RE = re.compile(
    r"uses:\s*([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)(?:/[^@\s]+)?@(\S+)"
    r"(?:\s*#\s*(v?\d[\w.-]*))?"
)
RELEASE_DOWNLOAD_RE = re.compile(
    r"github\.com/([\w.-]+/[\w.-]+)/releases/download/(v?[\d][\w.-]*)/"
)
DOCKER_ARG_RE = re.compile(r"^\s*ARG\s+([A-Za-z_][A-Za-z0-9_]*)=(\S+)\s*$", re.MULTILINE)
FROM_RE = re.compile(r"^FROM\s+(\S+):(\S+)", re.MULTILINE)
PYTHON_WORKFLOW_RE = re.compile(r"^\s*python-version:\s*[\"']?([^\"'\s#]+)", re.MULTILINE)
PYTHON_TAG_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
STABLE_TAG_RE = PYTHON_TAG_RE
ACTION_TAG_RE = re.compile(r"^v?(\d+)(?:\.(\d+))?(?:\.(\d+))?$")
GIT_SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")


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


@dataclass(frozen=True)
class ToolUpstreamSpec:
    tool_key: str
    installed_pattern: str
    kind: str
    repo_or_url: str
    tag_pattern: str
    exclude: ExcludeTag | None = None


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


def _exclude_kicad_development(_tag: str, values: tuple[int, ...]) -> bool:
    return len(values) > 1 and values[1] == 99


TOOL_UPSTREAM_SPECS = (
    ToolUpstreamSpec(
        "kicad-cli",
        r"^(\d+)\.(\d+)\.(\d+)$",
        "github-tags",
        "KiCad/kicad-source-mirror",
        r"^(\d+)\.(\d+)\.(\d+)$",
        _exclude_kicad_development,
    ),
    ToolUpstreamSpec(
        "ngspice",
        r"^(\d+)\.(\d+)$",
        "sourceforge-best-release",
        "https://sourceforge.net/projects/ngspice/best_release.json",
        r"^/ng-spice-rework/(\d+(?:\.\d+)?)/",
    ),
    ToolUpstreamSpec(
        "cmake",
        r"(\d+)\.(\d+)\.(\d+)",
        "github-tags",
        "Kitware/CMake",
        r"^v(\d+)\.(\d+)\.(\d+)$",
    ),
    ToolUpstreamSpec(
        "ninja",
        r"^(\d+)\.(\d+)\.(\d+)$",
        "github-tags",
        "ninja-build/ninja",
        r"^v(\d+)\.(\d+)\.(\d+)$",
    ),
    ToolUpstreamSpec(
        "ccache",
        r"(\d+)\.(\d+)\.(\d+)",
        "github-tags",
        "ccache/ccache",
        r"^v(\d+)\.(\d+)\.(\d+)$",
    ),
    ToolUpstreamSpec(
        "git",
        r"(\d+)\.(\d+)\.(\d+)",
        "github-tags",
        "git/git",
        r"^v(\d+)\.(\d+)\.(\d+)$",
    ),
    ToolUpstreamSpec(
        "python3.14",
        r"(\d+)\.(\d+)\.(\d+)",
        "github-tags",
        "python/cpython",
        r"^v(\d+)\.(\d+)\.(\d+)$",
    ),
)


def _default_fetch_json(url: str) -> Any:
    headers = {"Accept": "application/json"}
    if urlsplit(url).netloc == "api.github.com":
        token = os.environ.get("GITHUB_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"
    request = Request(url, headers=headers)
    with urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


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


def _default_list_remote_head(url: str) -> str:
    result = subprocess.run(
        ["git", "ls-remote", url, "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=20,
    )
    fields = result.stdout.split()
    if not fields or not GIT_SHA_RE.fullmatch(fields[0]):
        raise ValueError(f"git ls-remote returned no HEAD SHA for {url}")
    return fields[0]


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


def _default_run_uv(command: list[str], cwd: Path) -> str:
    environment = os.environ.copy()
    environment["UV_NO_PROGRESS"] = "1"
    result = subprocess.run(
        command,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        cwd=cwd,
        env=environment,
        timeout=600,
    )
    return result.stdout


def normalize_name(name: str) -> str:
    """Normalize a Python distribution name according to PEP 503."""
    return re.sub(r"[-_.]+", "-", name.lower())


def _package_name(requirement: str) -> str:
    match = PACKAGE_NAME_RE.match(requirement.strip())
    if match is None:
        raise ValueError(f"cannot parse dependency name: {requirement!r}")
    return normalize_name(match.group(0))


def _dict(value: Any, message: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(message)
    return cast(dict[str, Any], value)


def _project_data(repo_root: Path) -> dict[str, Any]:
    with (repo_root / "pyproject.toml").open("rb") as stream:
        return _dict(tomllib.load(stream), "pyproject.toml is not an object")


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
    groups = _dict(data.get("dependency-groups", {}), "[dependency-groups] is not a table")
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
    with (repo_root / "uv.lock").open("rb") as stream:
        payload: Any = tomllib.load(stream)
    lock_data = _dict(payload, "uv.lock is not an object")
    packages = lock_data.get("package")
    if not isinstance(packages, list):
        raise ValueError("uv.lock has no [[package]] entries")
    versions: dict[str, str] = {}
    for package in cast(list[Any], packages):
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
        payload = _dict(
            fetch_json(f"https://pypi.org/pypi/{name}/json"),
            f"PyPI response is invalid for {name}",
        )
        info = _dict(payload.get("info"), f"PyPI response has no info for {name}")
        latest = info.get("version")
        if not isinstance(latest, str) or not latest:
            raise ValueError(f"PyPI response has no version for {name}")
        statuses.append(
            DependencyStatus("pypi", name, current, latest, "pyproject.toml", latest != current)
        )
    return statuses


def check_pypi_lock(
    repo_root: Path,
    direct_names: set[str],
    *,
    run_uv: RunUv = _default_run_uv,
) -> list[DependencyStatus]:
    output = run_uv(["uv", "lock", "--upgrade", "--dry-run"], repo_root)
    patterns = (
        (re.compile(r"^Update (\S+) v(\S+) -> v(\S+)$"), "update"),
        (re.compile(r"^Add (\S+) v(\S+)$"), "add"),
        (re.compile(r"^Remove (\S+) v(\S+)$"), "remove"),
    )
    statuses: list[DependencyStatus] = []
    for line in output.splitlines():
        for pattern, kind in patterns:
            match = pattern.fullmatch(line)
            if match is None:
                continue
            groups = match.groups()
            name = groups[0]
            if normalize_name(name) in direct_names:
                break
            if kind == "update":
                current, latest, note = groups[1], groups[2], ""
            elif kind == "add":
                current, latest, note = "-", groups[1], "would be added"
            else:
                current, latest, note = groups[1], "-", "would be removed"
            statuses.append(
                DependencyStatus("pypi-lock", name, current, latest, "uv.lock", True, note)
            )
            break
    return statuses


def _highest_stable_tag(
    tags: list[str],
    pattern: re.Pattern[str],
    exclude: ExcludeTag | None = None,
) -> tuple[str, tuple[int, ...]]:
    candidates: list[tuple[tuple[int, ...], str]] = []
    for tag in tags:
        match = pattern.fullmatch(tag)
        if match is None:
            continue
        values = tuple(int(group or "0") for group in match.groups())
        if exclude is None or not exclude(tag, values):
            candidates.append((values, tag))
    if not candidates:
        raise ValueError("no stable remote tags matched the expected pattern")
    values, tag = max(candidates)
    return tag, values


def _numeric_greater(left: tuple[int, ...], right: tuple[int, ...]) -> bool:
    width = max(len(left), len(right))
    return (left + (0,) * (width - len(left))) > (right + (0,) * (width - len(right)))


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


def _sdk_pins(data: dict[str, Any]) -> dict[str, str]:
    project = _dict(data.get("project"), "pyproject.toml has no [project] table")
    dependencies = project.get("dependencies")
    if not isinstance(dependencies, list):
        raise ValueError("[project].dependencies is not an array")
    pins: dict[str, str] = {}
    for requirement in cast(list[Any], dependencies):
        if not isinstance(requirement, str):
            raise ValueError("[project].dependencies contains a non-string entry")
        name = _package_name(requirement)
        if name not in {"openhands-sdk", "openhands-tools", "openhands-workspace"}:
            continue
        match = re.search(r"==\s*([A-Za-z0-9][A-Za-z0-9._-]*)", requirement)
        if match is None:
            raise ValueError(f"{name} must have an exact pin")
        pins[name] = match.group(1)
    expected = {"openhands-sdk", "openhands-tools", "openhands-workspace"}
    missing = expected - pins.keys()
    if missing:
        raise ValueError(f"pyproject.toml has no exact pin for {sorted(missing)}")
    return pins


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
            "submodule",
            "software-agent-sdk",
            current,
            latest,
            ".gitmodules",
            current != latest or bool(note),
            note,
        )
    ]
    submodule_pin = current.removeprefix("v") if STABLE_TAG_RE.fullmatch(current) else None
    if submodule_pin is not None:
        pins = _sdk_pins(_project_data(repo_root))
        for name in ("openhands-sdk", "openhands-tools", "openhands-workspace"):
            pin = pins[name]
            if pin != submodule_pin:
                statuses.append(
                    DependencyStatus(
                        "submodule",
                        f"{name} pin",
                        pin,
                        submodule_pin,
                        "pyproject.toml",
                        True,
                        "pyproject.toml pin and submodule tag must stay in sync",
                    )
                )
    return statuses


def _numeric_version(value: str) -> tuple[int, ...]:
    match = ACTION_TAG_RE.fullmatch(value)
    if match is None:
        raise ValueError(f"not a numeric version: {value}")
    return tuple(int(group or "0") for group in match.groups() if group is not None)


def _version_outdated(current: tuple[int, ...], latest: tuple[int, ...]) -> bool:
    width = len(current)
    return latest[:width] > current


def _workflow_files(repo_root: Path) -> list[Path]:
    return sorted((repo_root / ".github" / "workflows").glob("*.yml"))


def check_github_actions(
    repo_root: Path,
    *,
    list_remote_tags: ListRemoteTags = _default_list_remote_tags,
) -> list[DependencyStatus]:
    found: dict[tuple[str, str], tuple[str, str, str]] = {}
    for workflow in _workflow_files(repo_root):
        for line in workflow.read_text(encoding="utf-8").splitlines():
            match = ACTION_RE.search(line)
            if match is None:
                continue
            repo, ref, comment_version = match.groups()
            key = (repo, ref)
            source = str(workflow.relative_to(repo_root))
            if key in found:
                old_repo, old_current, old_sources = found[key]
                found[key] = (old_repo, old_current, f"{old_sources}, {source}")
            else:
                found[key] = (repo, comment_version or ref, source)
    statuses: list[DependencyStatus] = []
    for repo, current, source in found.values():
        latest, latest_values = _highest_stable_tag(
            list_remote_tags(f"https://github.com/{repo}"),
            ACTION_TAG_RE,
        )
        statuses.append(
            DependencyStatus(
                "github-actions",
                repo,
                current,
                latest,
                source,
                _version_outdated(_numeric_version(current), latest_values),
            )
        )
    return statuses


def check_github_release_downloads(
    repo_root: Path,
    *,
    list_remote_tags: ListRemoteTags = _default_list_remote_tags,
) -> list[DependencyStatus]:
    found: dict[tuple[str, str], str] = {}
    for workflow in _workflow_files(repo_root):
        text = workflow.read_text(encoding="utf-8")
        for repo, current in RELEASE_DOWNLOAD_RE.findall(text):
            key = (repo, current)
            source = str(workflow.relative_to(repo_root))
            found[key] = f"{found[key]}, {source}" if key in found else source
    statuses: list[DependencyStatus] = []
    for (repo, current), source in found.items():
        latest, latest_values = _highest_stable_tag(
            list_remote_tags(f"https://github.com/{repo}"),
            ACTION_TAG_RE,
        )
        statuses.append(
            DependencyStatus(
                "github-release-download",
                repo,
                current,
                latest,
                source,
                _version_outdated(_numeric_version(current), latest_values),
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
        repo = spec.repo.format(major=current_values[0]) if "{major}" in spec.repo else spec.repo
        latest, latest_values = _highest_stable_tag(
            list_remote_tags(f"https://github.com/{repo}"),
            pattern,
        )
        statuses.append(
            DependencyStatus(
                "docker-arg",
                spec.arg,
                current,
                latest,
                "docker/acd-tools.Dockerfile",
                _numeric_greater(latest_values, current_values),
            )
        )
    return statuses


def check_docker_base(
    repo_root: Path,
    *,
    fetch_json: FetchJson = _default_fetch_json,
) -> list[DependencyStatus]:
    path = repo_root / "docker" / "acd-tools.Dockerfile"
    matches = FROM_RE.findall(path.read_text(encoding="utf-8"))
    if not matches:
        raise ValueError("Dockerfile has no versioned FROM image")
    image, current = matches[0]
    if "/" in image:
        raise ValueError(f"Docker base image is not an official image: {image}")
    current_match = re.fullmatch(r"(\d{2})\.(\d{2})", current)
    if current_match is None:
        raise ValueError(f"Docker base image has invalid YY.MM version: {current}")
    current_values = tuple(int(group) for group in current_match.groups())
    url = f"https://hub.docker.com/v2/repositories/library/{image}/tags?page_size=100"
    tags: list[str] = []
    for _page in range(20):
        payload = _dict(fetch_json(url), f"Docker Hub response is invalid: {url}")
        results = payload.get("results")
        if not isinstance(results, list):
            raise ValueError(f"Docker Hub response has no results: {url}")
        for result in cast(list[Any], results):
            result_data = _dict(result, "Docker Hub result is malformed")
            name = result_data.get("name")
            if isinstance(name, str):
                tags.append(name)
        next_url = payload.get("next")
        if next_url is None:
            break
        if not isinstance(next_url, str) or not next_url:
            raise ValueError("Docker Hub next link is malformed")
        url = next_url
    else:
        raise ValueError("Docker Hub pagination exceeded 20 pages")
    latest, latest_values = _highest_stable_tag(
        tags,
        re.compile(r"^(\d{2})\.(\d{2})$"),
        exclude=lambda _tag, values: values[0] % 2 != 0 or values[1] != 4,
    )
    return [
        DependencyStatus(
            "docker-base",
            image,
            current,
            latest,
            "docker/acd-tools.Dockerfile",
            _numeric_greater(latest_values, current_values),
        )
    ]


def _tool_lock(repo_root: Path) -> dict[str, str]:
    with (repo_root / "docker" / "image-digests.json").open(encoding="utf-8") as stream:
        payload: Any = json.load(stream)
    root = _dict(payload, "image digest lock is not an object")
    tools_entry = _dict(root.get("acd_tools"), "image lock has no acd_tools")
    tools = _dict(tools_entry.get("tools"), "image lock has no tools")
    values: dict[str, str] = {}
    for name, value in tools.items():
        if not isinstance(value, str):
            raise ValueError(f"tool version is not a string: {name}")
        values[name] = value
    return values


def _installed_version(value: str, pattern: str, name: str) -> tuple[str, tuple[int, ...]]:
    match = re.search(pattern, value)
    if match is None:
        raise ValueError(f"cannot parse installed version for {name}: {value}")
    groups = tuple(group for group in match.groups() if group is not None)
    return ".".join(groups), tuple(int(group) for group in groups)


def _sourceforge_version(payload: Any, pattern: str) -> tuple[str, tuple[int, ...]]:
    release = _dict(payload, "SourceForge response is not an object").get("release")
    release_data = _dict(release, "SourceForge response has no release")
    filename = release_data.get("filename")
    if not isinstance(filename, str):
        raise ValueError("SourceForge release has no filename")
    match = re.search(pattern, filename)
    if match is None:
        raise ValueError(f"cannot parse SourceForge version: {filename}")
    value = match.group(1)
    values = tuple(int(part) for part in value.split("."))
    return value, values


def check_tool_upstream(
    repo_root: Path,
    *,
    fetch_json: FetchJson = _default_fetch_json,
    list_remote_tags: ListRemoteTags = _default_list_remote_tags,
) -> list[DependencyStatus]:
    tools = _tool_lock(repo_root)
    statuses: list[DependencyStatus] = []
    for spec in TOOL_UPSTREAM_SPECS:
        installed = tools.get(spec.tool_key)
        if installed is None:
            raise ValueError(f"image lock is missing tool {spec.tool_key}")
        current, current_values = _installed_version(
            installed,
            spec.installed_pattern,
            spec.tool_key,
        )
        if spec.kind == "github-tags":
            tags = list_remote_tags(f"https://github.com/{spec.repo_or_url}")
            pattern = re.compile(spec.tag_pattern)
            if spec.tool_key == "python3.14":
                tags = [
                    tag
                    for tag in tags
                    if (match := PYTHON_TAG_RE.fullmatch(tag))
                    and (int(match.group(1)), int(match.group(2))) == current_values[:2]
                ]
            latest_tag, latest_values = _highest_stable_tag(tags, pattern, spec.exclude)
            latest = latest_tag.removeprefix("v")
        elif spec.kind == "sourceforge-best-release":
            latest, latest_values = _sourceforge_version(
                fetch_json(spec.repo_or_url),
                spec.tag_pattern,
            )
        else:
            raise ValueError(f"unknown tool upstream kind: {spec.kind}")
        statuses.append(
            DependencyStatus(
                "tool-upstream",
                spec.tool_key,
                current,
                latest,
                "docker/image-digests.json",
                _numeric_greater(latest_values, current_values),
            )
        )
    cpython_tags = list_remote_tags("https://github.com/python/cpython")
    stable_minors = sorted(
        {
            (int(match.group(1)), int(match.group(2)))
            for tag in cpython_tags
            if (match := PYTHON_TAG_RE.fullmatch(tag))
        }
    )
    if not stable_minors:
        raise ValueError("no stable CPython minor series found")
    python_current = _installed_version(tools["python3.14"], r"(\d+)\.(\d+)\.(\d+)", "python3.14")
    latest_minor = ".".join(str(part) for part in stable_minors[-1])
    statuses.append(
        DependencyStatus(
            "tool-upstream",
            "python (minor series)",
            ".".join(str(part) for part in python_current[1][:2]),
            latest_minor,
            "docker/image-digests.json",
            stable_minors[-1] > python_current[1][:2],
            "informational",
        )
    )
    return statuses


def check_semeru_majors(
    repo_root: Path,
    *,
    fetch_json: FetchJson = _default_fetch_json,
) -> list[DependencyStatus]:
    values = dict(
        DOCKER_ARG_RE.findall(
            (repo_root / "docker" / "acd-tools.Dockerfile").read_text(encoding="utf-8")
        )
    )
    current = values.get("SEMERU_JRE_VERSION")
    if current is None:
        raise ValueError("Dockerfile is missing required ARG SEMERU_JRE_VERSION")
    match = re.fullmatch(r"(\d+)\.\d+\.\d+\.\d+", current)
    if match is None:
        raise ValueError(f"invalid SEMERU_JRE_VERSION: {current}")
    current_major = int(match.group(1))
    majors: list[int] = []
    for page in range(1, 11):
        url = f"https://api.github.com/orgs/ibmruntimes/repos?per_page=100&page={page}"
        payload = fetch_json(url)
        if not isinstance(payload, list):
            raise ValueError("GitHub repositories response is not an array")
        if not payload:
            break
        for repository in cast(list[Any], payload):
            repository_data = _dict(repository, "GitHub repository entry is malformed")
            name = repository_data.get("name")
            if isinstance(name, str):
                repo_match = re.fullmatch(r"semeru(\d+)-binaries", name)
                if repo_match:
                    majors.append(int(repo_match.group(1)))
    else:
        raise ValueError("GitHub repository pagination exceeded 10 pages")
    if not majors or max(majors) <= current_major:
        return []
    latest = max(majors)
    return [
        DependencyStatus(
            "docker-arg",
            "SEMERU_JRE_VERSION (major)",
            str(current_major),
            str(latest),
            "docker/acd-tools.Dockerfile",
            True,
            f"newer Java major available in ibmruntimes/semeru{latest}-binaries",
        )
    ]


def check_git_pin(
    repo_root: Path,
    *,
    list_remote_head: ListRemoteHead = _default_list_remote_head,
) -> list[DependencyStatus]:
    text = (repo_root / "libraries" / "README.md").read_text(encoding="utf-8")
    url_match = re.search(r"- 取得元URL:\s*`([^`]+)`", text)
    commit_match = re.search(r"- 取得commit:\s*`([^`]+)`", text)
    if url_match is None or commit_match is None:
        raise ValueError("libraries/README.md is missing URL or commit pin")
    url = url_match.group(1)
    current = commit_match.group(1)
    if not GIT_SHA_RE.fullmatch(current):
        raise ValueError("libraries/README.md has an invalid commit pin")
    latest_full = list_remote_head(url)
    if not GIT_SHA_RE.fullmatch(latest_full):
        raise ValueError(f"invalid remote HEAD SHA for {url}")
    return [
        DependencyStatus(
            "git-pin",
            "espressif/kicad-libraries",
            current,
            latest_full[:12],
            "libraries/README.md",
            current.lower() != latest_full.lower(),
            "default branch HEAD",
        )
    ]


def _python_minor(value: str, source: str) -> tuple[int, int]:
    match = re.fullmatch(r"(\d+)\.(\d+)", value)
    if match is None:
        raise ValueError(f"invalid Python minor version in {source}: {value}")
    return int(match.group(1)), int(match.group(2))


def check_python_versions(
    repo_root: Path,
    *,
    list_remote_tags: ListRemoteTags = _default_list_remote_tags,
) -> list[DependencyStatus]:
    values: list[tuple[str, str]] = []
    for workflow in _workflow_files(repo_root):
        text = workflow.read_text(encoding="utf-8")
        values.extend(
            (value, str(workflow.relative_to(repo_root)))
            for value in PYTHON_WORKFLOW_RE.findall(text)
        )
    docker_text = (repo_root / "docker" / "acd-tools.Dockerfile").read_text(encoding="utf-8")
    docker_values = dict(DOCKER_ARG_RE.findall(docker_text))
    docker_python = docker_values.get("ESP_IDF_PYTHON_VERSION")
    if docker_python is None:
        raise ValueError("Dockerfile is missing required ARG ESP_IDF_PYTHON_VERSION")
    values.append((docker_python, "docker/acd-tools.Dockerfile"))
    project = _dict(
        _project_data(repo_root).get("project"), "pyproject.toml has no [project] table"
    )
    requires_python = project.get("requires-python")
    if not isinstance(requires_python, str):
        raise ValueError("pyproject.toml has no requires-python")
    requires_match = re.search(r"(\d+)\.(\d+)", requires_python)
    if requires_match is None:
        raise ValueError(f"invalid requires-python: {requires_python}")
    values.append((f"{requires_match.group(1)}.{requires_match.group(2)}", "pyproject.toml"))
    tags = list_remote_tags("https://github.com/python/cpython")
    stable_minors = sorted(
        {
            (int(match.group(1)), int(match.group(2)))
            for tag in tags
            if (match := PYTHON_TAG_RE.fullmatch(tag))
        }
    )
    if not stable_minors:
        raise ValueError("no stable CPython minor series found")
    latest = ".".join(str(part) for part in stable_minors[-1])
    statuses: list[DependencyStatus] = []
    seen: set[tuple[str, str]] = set()
    for value, source in values:
        key = (value, source)
        if key in seen:
            continue
        seen.add(key)
        current_minor = _python_minor(value, source)
        statuses.append(
            DependencyStatus(
                "python-version",
                f"Python version ({source})",
                value,
                latest,
                source,
                current_minor < stable_minors[-1],
            )
        )
    return statuses


def check_dependency_updates(
    repo_root: Path,
    *,
    fetch_json: FetchJson = _default_fetch_json,
    list_remote_tags: ListRemoteTags = _default_list_remote_tags,
    list_remote_head: ListRemoteHead = _default_list_remote_head,
    run_git: RunGit = _default_run_git,
    run_uv: RunUv = _default_run_uv,
) -> list[DependencyStatus]:
    tag_cache: dict[str, list[str]] = {}

    def cached_tags(url: str) -> list[str]:
        if url not in tag_cache:
            tag_cache[url] = list_remote_tags(url)
        return tag_cache[url]

    pypi = check_pypi(repo_root, fetch_json=fetch_json)
    direct_names = {status.name for status in pypi}
    return [
        *pypi,
        *check_pypi_lock(repo_root, direct_names, run_uv=run_uv),
        *check_submodule(repo_root, list_remote_tags=cached_tags, run_git=run_git),
        *check_github_actions(repo_root, list_remote_tags=cached_tags),
        *check_github_release_downloads(repo_root, list_remote_tags=cached_tags),
        *check_docker_base(repo_root, fetch_json=fetch_json),
        *check_docker_args(repo_root, list_remote_tags=cached_tags),
        *check_semeru_majors(repo_root, fetch_json=fetch_json),
        *check_tool_upstream(repo_root, fetch_json=fetch_json, list_remote_tags=cached_tags),
        *check_python_versions(repo_root, list_remote_tags=cached_tags),
        *check_git_pin(repo_root, list_remote_head=list_remote_head),
    ]


def render_markdown(statuses: list[DependencyStatus]) -> str:
    labels = {
        "pypi": "PyPI（直接依存）",
        "pypi-lock": "PyPI（uv.lock間接依存）",
        "submodule": "submodule",
        "github-actions": "GitHub Actions",
        "github-release-download": "GitHub release download",
        "docker-base": "Docker base image",
        "docker-arg": "Docker ARG",
        "tool-upstream": "ツール上流版",
        "python-version": "Python版",
        "git-pin": "git pin",
    }
    lines = ["# 依存アップデート確認レポート", ""]
    for surface, label in labels.items():
        surface_statuses = [status for status in statuses if status.surface == surface]
        lines.extend([f"## {label}", ""])
        if surface == "pypi-lock":
            lines.append(
                "間接依存はdriftのある項目のみ表示（`uv lock --upgrade --dry-run`の出力に基づく）"
            )
            lines.append("")
        if not surface_statuses:
            lines.extend(["確認対象なし", ""])
            continue
        lines.extend(
            [
                "| 依存 | 現在 | 最新 | 状態 | 参照 |",
                "| --- | --- | --- | --- | --- |",
            ]
        )
        ordered_statuses = [
            status
            for outdated in (True, False)
            for status in surface_statuses
            if status.outdated is outdated
        ]
        for status in ordered_statuses:
            latest = status.latest
            if status.note:
                latest = f"{latest} ({status.note})"
            state = "更新あり" if status.outdated else "最新"
            lines.append(
                f"| {status.name} | {status.current} | {latest} | {state} | {status.source} |"
            )
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
