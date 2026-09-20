"""Shared helpers and constants for the install doctor checks.

This package is part of the install doctor L3 observation and uses only the
standard library; it never imports ``acd``.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, cast

SHA256_RE = re.compile(r"^[0-9a-f]{40}$")
SEMVER_RE = re.compile(r"^v\d+\.\d+\.\d+$")
HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
HOOK_PLUGIN_PATH_RE = re.compile(r"\$\{[^}]+\}(/[^\s'\";]+\.py)")
HOOK_PATH_RE = re.compile(r"(?:^|\s)([A-Za-z0-9_.-]+/(?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]+\.py)")
LIST_ITEM_RE = re.compile(r"^\s+-\s*(\S+)\s*$")
HOOK_INTERPRETER_RE = re.compile(r"(?:uv run python|python3?)\s+[\"']?$")
HOST_MEMORY_LIMIT_BYTES = 8 * 1024 * 1024 * 1024
HOST_MEMORY_HEADROOM_BYTES = 512 * 1024 * 1024
HOST_JVM_MAX_HEAP_BYTES = 2 * 1024 * 1024 * 1024
HOST_JVM_NON_HEAP_RESERVE_BYTES = 1024 * 1024 * 1024
HOST_MIN_CPU_COUNT = 2
HOST_MIN_DISK_FREE_BYTES = 8 * 1024 * 1024 * 1024
MIB = 1024 * 1024


def check_result(
    name: str,
    required: bool,
    result: str,
    detail: str,
    observed_version: str | None = None,
    *,
    path: str,
    next_step: str | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "required": required,
        "result": result,
        "detail": detail,
        "observed_version": observed_version,
        "path": path,
        "next_step": next_step,
    }


def relative_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def front_matter(text: str) -> dict[str, str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("front-matter must start with ---")
    try:
        end = lines.index("---", 1)
    except ValueError as exc:
        raise ValueError("front-matter closing --- is missing") from exc
    fields: dict[str, str] = {}
    for line in lines[1:end]:
        if not line.strip() or line[0].isspace() or ":" not in line:
            continue
        key, value = line.split(":", 1)
        fields[key.strip()] = value.strip()
    return fields


def front_matter_list(text: str, key: str) -> list[str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("front-matter must start with ---")
    try:
        end = lines.index("---", 1)
    except ValueError as exc:
        raise ValueError("front-matter closing --- is missing") from exc
    items: list[str] = []
    inside = False
    for line in lines[1:end]:
        if not inside:
            inside = line.strip() == f"{key}:"
            continue
        item = LIST_ITEM_RE.match(line)
        if item is None:
            break
        items.append(item.group(1))
    return items


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def plugin_asset_path(asset_path: str) -> str:
    prefix = "plugins/acd/"
    return asset_path[len(prefix) :] if asset_path.startswith(prefix) else asset_path


def hook_references(
    document: Any, plugin_root: Path
) -> tuple[list[str], list[str], list[tuple[str, Path]]]:
    plugin_refs: list[str] = []
    external_refs: list[str] = []
    direct_plugin_refs: list[tuple[str, Path]] = []

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            for child in cast(dict[str, Any], value).values():
                visit(child)
        elif isinstance(value, list):
            for child in cast(list[Any], value):
                visit(child)
        elif isinstance(value, str) and ".py" in value:
            for match in HOOK_PLUGIN_PATH_RE.finditer(value):
                relative = match.group(1).lstrip("/")
                target = plugin_root / relative
                plugin_refs.append(f"{relative}: {'present' if target.is_file() else 'missing'}")
                if HOOK_INTERPRETER_RE.search(value[: match.start()]) is None:
                    direct_plugin_refs.append((relative, target))
            for match in HOOK_PATH_RE.finditer(value):
                relative = match.group(1)
                if not relative.startswith(("hooks/", "skills/", "agents/")):
                    external_refs.append(relative)

    visit(document)
    return plugin_refs, sorted(set(external_refs)), direct_plugin_refs


def run_version(
    command: str,
    args: list[str],
    version_pattern: str,
    *,
    allow_nonzero_exit: bool = False,
) -> str | None:
    path = shutil.which(command)
    if path is None:
        return None
    try:
        completed = subprocess.run(
            [path, *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    output = f"{completed.stdout}\n{completed.stderr}".strip()
    match = re.search(version_pattern, output)
    if match is None or (completed.returncode != 0 and not allow_nonzero_exit):
        return "unknown"
    return match.group(1)


def in_container() -> bool:
    return Path("/.dockerenv").exists() or bool(os.environ.get("ACD_HOME"))


PLUGIN_ROOT = Path(__file__).resolve().parents[4]


def locked_server_image(workspace: Path | None) -> tuple[str | None, str | None]:
    plugin_root = PLUGIN_ROOT
    candidates: list[Path] = []
    if workspace is not None:
        candidates.append(workspace / "docker" / "image-digests.json")
    candidates.extend(
        (
            plugin_root.parents[1] / "docker" / "image-digests.json",
            Path("/opt/acd/docker/image-digests.json"),
        )
    )
    seen: set[Path] = set()
    for path in candidates:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if not resolved.is_file():
            continue
        try:
            document = read_json(resolved)
            server = document["acd_server"]
            image = server["image"]
            digest = server["digest"]
            if (
                not isinstance(image, str)
                or not image
                or any(character.isspace() for character in image)
                or "@" in image
                or not isinstance(digest, str)
            ):
                raise ValueError("acd_server image or digest is invalid")
            if HASH_RE.fullmatch(digest) is None:
                raise ValueError(f"invalid image digest: {digest!r}")
        except (
            OSError,
            UnicodeDecodeError,
            json.JSONDecodeError,
            KeyError,
            TypeError,
            ValueError,
        ) as exc:
            return None, f"{resolved} could not be inspected: {exc}"
        return f"{image}@{digest}", None
    searched = ", ".join(str(path) for path in candidates)
    return None, f"locked server image manifest was not found; searched: {searched}"


def docker_image_command(
    reference: str, script: str, *, timeout: float
) -> tuple[str | None, str | None]:
    docker = shutil.which("docker")
    if docker is None:
        return None, "docker CLI is absent"
    try:
        completed = subprocess.run(
            [
                docker,
                "run",
                "--rm",
                "--entrypoint",
                "",
                reference,
                "sh",
                "-lc",
                script,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, f"docker run failed: {exc}"
    output = f"{completed.stdout}\n{completed.stderr}".strip()
    if completed.returncode != 0:
        return None, output or f"docker run exited with {completed.returncode}"
    return output, None


def pull_timeout() -> float:
    raw = os.environ.get("ACD_DOCTOR_PULL_TIMEOUT_SECONDS", "3600")
    try:
        value = float(raw)
    except ValueError:
        return 3600
    return value if value > 0 else 3600


def image_section(output: str, name: str) -> str:
    match = re.search(
        rf"^=== {re.escape(name)} ===\n(.*?)(?=^=== |\Z)",
        output,
        flags=re.MULTILINE | re.DOTALL,
    )
    return match.group(1).strip() if match else ""
