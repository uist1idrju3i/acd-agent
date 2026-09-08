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
FAIL_CLOSED_CONTEXT = (
    "Authoritative tools are unavailable inside the locked image; "
    "relevant gates fail-closed."
)


def _lock_candidates(root: Path) -> list[Path]:
    """Candidate ``docker/image-digests.json`` paths, in resolution order.

    The first readable and valid lock wins: the session project dir, the
    workspace recorded by the bootstrap record, the checkout containing
    ``$ACD_PLUGIN_ROOT``, the checkout containing this script, and the
    in-image ACD bundle.
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
    return f"{FAIL_CLOSED_CONTEXT} (image lock not found; searched: {searched})"


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
    reference, _error, _used = _locked_image(root)
    if reference is None:
        context = _fail_closed_context(root)
    else:
        versions = _probe(root, reference)
        context = (
            f"Authoritative tools observed inside the locked image: {versions}."
            if versions is not None
            else FAIL_CLOSED_CONTEXT
        )
    result(additionalContext=context)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
