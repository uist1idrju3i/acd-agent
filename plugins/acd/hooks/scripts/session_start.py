"""Inject deterministic external tool probe results into the session."""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, cast

from common import event, project_dir, result

HASH_RE = re.compile(r"sha256:[0-9a-f]{64}")
PROFILE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
PERSISTENCE_DIR_ENV = "OH_PERSISTENCE_DIR"
WORKSPACE_REGISTRY_ENV = "ACD_WORKSPACE_REGISTRY"
FAIL_CLOSED_CONTEXT = (
    "Authoritative tools are unavailable inside the locked image; "
    "relevant gates fail-closed."
)


def _profile_store_path() -> Path:
    persistence_dir = os.environ.get(PERSISTENCE_DIR_ENV)
    if persistence_dir:
        path = Path(persistence_dir).expanduser()
        if not path.is_absolute():
            path = Path.cwd() / path
        return path / "profiles"
    return Path.home() / ".openhands" / "profiles"


def _saved_llm_profiles() -> tuple[Path, list[tuple[str, str]]]:
    profile_dir = _profile_store_path()
    profiles: list[tuple[str, str]] = []
    try:
        paths = sorted(profile_dir.glob("*.json"))
    except OSError:
        return profile_dir, profiles
    for path in paths:
        if PROFILE_NAME_RE.fullmatch(path.stem) is None:
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        model = cast(dict[str, Any], payload).get("model")
        if isinstance(model, str) and model.strip():
            profiles.append((path.stem, model))
    return profile_dir, profiles


def _vision_context() -> str:
    profile_dir, profiles = _saved_llm_profiles()
    if profiles:
        listing = ", ".join(f"{name}:{model}" for name, model in profiles)
        return (
            f"vision inspection: profiles={len(profiles)} ({listing}); "
            "inspect_image_with_vision is attached only when the active model "
            "or a saved profile is vision-capable"
        )
    return (
        "vision inspection: no saved LLM profile found at "
        f"{profile_dir}; inspect_image_with_vision will be unavailable unless "
        "the active model is vision-capable"
    )


def _workspace_registry_path() -> Path:
    configured = os.environ.get(WORKSPACE_REGISTRY_ENV)
    if configured:
        path = Path(configured).expanduser()
        return path if path.is_absolute() else Path.cwd() / path
    return Path.home() / ".openhands" / "acd" / "workspaces.json"


def _workspace_registry_entries() -> tuple[Path, list[dict[str, Any]]]:
    path = _workspace_registry_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return path, []
    if not isinstance(payload, dict):
        return path, []
    entries = cast(dict[str, Any], payload).get("workspaces")
    if not isinstance(entries, list):
        return path, []
    valid: list[dict[str, Any]] = []
    for raw_entry in cast(list[Any], entries):
        if not isinstance(raw_entry, dict):
            continue
        entry = cast(dict[str, Any], raw_entry)
        workspace_path = entry.get("workspace_path")
        if isinstance(workspace_path, str) and workspace_path:
            valid.append(entry)
    valid.sort(
        key=lambda entry: str(entry.get("registered_at", "")),
        reverse=True,
    )
    return path, valid


def _lock_candidates(root: Path) -> list[Path]:
    """Candidate ``docker/image-digests.json`` paths, in resolution order.

    The first readable and valid lock wins: the session project dir, the
    workspace recorded by the bootstrap record, the checkout containing
    the workspace registry, the checkout containing ``$ACD_PLUGIN_ROOT``, the
    checkout containing this script, and the in-image ACD bundle. Registry
    entries are considered from most recent to oldest.
    """
    candidates = [root / "docker" / "image-digests.json"]
    record = root / ".openhands" / "bootstrap-record.json"
    try:
        payload = json.loads(record.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        payload = None
    if isinstance(payload, dict):
        workspace = cast(dict[str, Any], payload).get("workspace_path")
        if isinstance(workspace, str) and workspace:
            candidates.append(Path(workspace) / "docker" / "image-digests.json")
    _registry_path, registry_entries = _workspace_registry_entries()
    for entry in registry_entries:
        candidates.append(
            Path(cast(str, entry["workspace_path"]))
            / "docker"
            / "image-digests.json"
        )
    plugin_root = os.environ.get("ACD_PLUGIN_ROOT")
    if plugin_root:
        with contextlib.suppress(OSError, IndexError):
            candidates.append(
                Path(plugin_root).resolve().parents[1]
                / "docker" / "image-digests.json"
            )
    with contextlib.suppress(OSError, IndexError):
        candidates.append(
            Path(__file__).resolve().parents[4] / "docker" / "image-digests.json"
        )
    candidates.append(Path("/opt/acd/docker/image-digests.json"))
    seen: set[Path] = set()
    unique: list[Path] = []
    for candidate in candidates:
        if candidate not in seen:
            seen.add(candidate)
            unique.append(candidate)
    return unique


def _locked_image(root: Path) -> tuple[str | None, str | None, Path | None]:
    """Resolve the locked server image, returning the lock path that was used."""
    error: str | None = None
    for path in _lock_candidates(root):
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
            server = document["acd_server"]
            image = server["image"]
            digest = server["digest"]
            if (
                not isinstance(image, str)
                or not image
                or any(character.isspace() for character in image)
                or "@" in image
                or not isinstance(digest, str)
                or HASH_RE.fullmatch(digest) is None
            ):
                raise ValueError("acd_server image or digest is invalid")
        except (
            OSError,
            UnicodeDecodeError,
            json.JSONDecodeError,
            KeyError,
            TypeError,
            ValueError,
        ) as exc:
            error = f"locked server image manifest is invalid: {exc}"
            continue
        return f"{image}@{digest}", None, path
    return None, error, None


def _fail_closed_context(root: Path) -> str:
    searched = ", ".join(str(path) for path in _lock_candidates(root))
    registry_path, entries = _workspace_registry_entries()
    registry_state = f"{len(entries)} entries" if entries else "missing"
    return (
        f"{FAIL_CLOSED_CONTEXT} (image lock not found; searched: {searched}; "
        f"workspace registry: {registry_path} ({registry_state}))"
    )


def _section(output: str, name: str) -> str:
    match = re.search(
        rf"^=== {re.escape(name)} ===\n(.*?)(?=^=== |\Z)",
        output,
        flags=re.MULTILINE | re.DOTALL,
    )
    return match.group(1).strip() if match else ""


def _probe(root: Path, reference: str | None = None) -> str | None:
    if reference is None:
        reference, _error, _path = _locked_image(root)
    if reference is None:
        return None
    docker = shutil.which("docker")
    if docker is None:
        return None
    script = (
        "printf '%s\\n' '=== kicad-cli ==='; "
        "kicad-cli version 2>&1 || true; "
        "printf '%s\\n' '=== freerouting ==='; "
        "freerouting --version 2>&1 || true; "
        "printf '%s\\n' '=== qemu-system-riscv32 ==='; "
        "qemu-system-riscv32 --version 2>&1 || true; "
        "printf '%s\\n' '=== cmake ==='; "
        "cmake --version 2>&1 || true"
    )
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
            cwd=root,
            text=True,
            encoding="utf-8",
            capture_output=True,
            timeout=60,
            check=False,
            env=os.environ.copy(),
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    output = f"{completed.stdout}\n{completed.stderr}"
    patterns = {
        "kicad-cli": r"([0-9]+\.[0-9]+\.[0-9]+)",
        "freerouting": r"Freerouting v([0-9]+\.[0-9]+\.?[0-9]*)",
        "qemu-system-riscv32": r"QEMU emulator version ([^\s]+)",
        "cmake": r"cmake version ([^\s]+)",
    }
    versions: dict[str, str] = {}
    for name, pattern in patterns.items():
        match = re.search(pattern, _section(output, name))
        if match is None:
            return None
        versions[name] = match.group(1)
    return ", ".join(f"{name}={version}" for name, version in versions.items())


def main() -> int:
    root = project_dir(event())
    vision_context = _vision_context()
    reference, _error, _used = _locked_image(root)
    if reference is None:
        context = f"{_fail_closed_context(root)}\n{vision_context}"
    else:
        versions = _probe(root, reference)
        context = (
            f"Authoritative tools observed inside the locked image: {versions}."
            if versions is not None
            else FAIL_CLOSED_CONTEXT
        )
        if _used is not None:
            context = f"Locked image resolved from {_used}.\n{context}"
        context = f"{context}\n{vision_context}"
    result(additionalContext=context)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
