"""Run deterministic ACD commands through a digest-pinned server workspace."""

from __future__ import annotations

import json
import os
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

from openhands.sdk.workspace import LocalWorkspace
from openhands.workspace import DockerWorkspace

from acd.core.naming import artifact_prefix, required_evidence_ids
from acd.schema.design_graph import DesignGraph

CONTAINER_REPOSITORY = Path("/acd-src")
CONTAINER_WORKTREE = Path("/workspace/acd")
CONTAINER_BUNDLE = Path("/opt/acd")
_DIGEST = re.compile(r"sha256:[0-9a-fA-F]{64}\Z")

WorkspaceSource = Literal["mounted", "bundled"]


@dataclass(frozen=True)
class WorkspaceDefaults:
    command: str
    download_files: tuple[str, ...]
    required_evidence_ids: frozenset[str]


def workspace_defaults(graph_id: str) -> WorkspaceDefaults:
    prefix = artifact_prefix(graph_id)
    return WorkspaceDefaults(
        command=(
            "uv run python scripts/run_"
            f"{prefix}_enclosure_pipeline.py --out out/{prefix}-enclosure"
        ),
        download_files=(
            f"out/{prefix}/evidence-electrical.json",
            f"out/{prefix}-enclosure/evidence-mechanical.json",
        ),
        required_evidence_ids=required_evidence_ids(graph_id),
    )


def load_workspace_graph(path: Path) -> DesignGraph:
    try:
        return DesignGraph.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"design graph could not be loaded: {path}") from exc


@dataclass(frozen=True)
class ImageReference:
    digest: str
    source: str


@dataclass(frozen=True)
class WorkspaceResult:
    digest: str
    source: str
    exit_code: int
    stdout: str
    stderr: str
    downloaded_files: tuple[Path, ...]


@dataclass(frozen=True)
class ProvisionalWorkspaceResult:
    exit_code: int
    stdout: str
    stderr: str
    execution_context: Literal["host"] = "host"
    authoritative: Literal[False] = False


def _inspect(
    image: str,
    *,
    format_string: str,
    run: Callable[..., subprocess.CompletedProcess[str]],
) -> subprocess.CompletedProcess[str]:
    return run(
        ["docker", "image", "inspect", f"--format={format_string}", image],
        capture_output=True,
        text=True,
        check=False,
    )


def resolve_image_digest(
    image: str,
    *,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> ImageReference | None:
    """Resolve a content address for an image, or return ``None``."""
    try:
        repo_digests = _inspect(image, format_string="{{json .RepoDigests}}", run=run)
    except FileNotFoundError:
        return None
    if repo_digests.returncode == 0:
        try:
            values = cast(object, json.loads(repo_digests.stdout))
        except json.JSONDecodeError:
            values = []
        if isinstance(values, list):
            for value in cast(list[object], values):
                if not isinstance(value, str):
                    continue
                candidate = value.rsplit("@", 1)[-1]
                if _DIGEST.fullmatch(candidate):
                    return ImageReference(candidate, "RepoDigests")

    try:
        image_id = _inspect(image, format_string="{{.Id}}", run=run)
    except FileNotFoundError:
        return None
    candidate = image_id.stdout.strip()
    if image_id.returncode == 0 and _DIGEST.fullmatch(candidate):
        return ImageReference(candidate, "image ID")
    return None


def run_command_in_workspace(
    *,
    image: str,
    command: str,
    repository: Path,
    download_files: tuple[str, ...],
    workspace_factory: Callable[..., Any] | None = None,
    source: WorkspaceSource = "mounted",
) -> WorkspaceResult:
    """Run one command in a DockerWorkspace using a resolved server digest.

    With ``source="mounted"`` the host repository is mounted read-only and
    copied into the container worktree. With ``source="bundled"`` the ACD
    source, pipeline scripts and fixtures baked into the locked image are used
    and no repository is mounted; a missing or incomplete bundle stops the run.
    """
    if not image.strip():
        raise ValueError("server image must not be empty")
    if source not in ("mounted", "bundled"):
        raise ValueError(f"unknown workspace source: {source!r}")
    reference = resolve_image_digest(image)
    if reference is None:
        raise ValueError("server image digest could not be resolved; refusing to execute")

    factory = workspace_factory or DockerWorkspace
    previous_digest = os.environ.get("ACD_CONTAINER_IMAGE_DIGEST")
    previous_marker = os.environ.get("ACD_IN_CONTAINER")
    os.environ["ACD_CONTAINER_IMAGE_DIGEST"] = reference.digest
    os.environ["ACD_IN_CONTAINER"] = "1"
    downloaded: list[Path] = []
    worktree = CONTAINER_BUNDLE if source == "bundled" else CONTAINER_WORKTREE
    try:
        constructor_kwargs: dict[str, Any] = {
            "server_image": image,
            "forward_env": ["ACD_CONTAINER_IMAGE_DIGEST", "ACD_IN_CONTAINER"],
        }
        if source == "mounted":
            constructor_kwargs["volumes"] = [
                f"{repository.resolve()}:{CONTAINER_REPOSITORY}:ro"
            ]
        workspace = factory(**constructor_kwargs)
        with workspace:
            if source == "bundled":
                setup = (
                    f"test -f {CONTAINER_BUNDLE / 'pyproject.toml'} && "
                    f"test -f {CONTAINER_BUNDLE / 'uv.lock'} && "
                    f"test -d {CONTAINER_BUNDLE / 'src' / 'acd'} && "
                    f"test -d {CONTAINER_BUNDLE / 'scripts'} && "
                    f"test -d {CONTAINER_BUNDLE / 'fixtures'} && "
                    f"test -d {CONTAINER_BUNDLE / '.venv'} && "
                    f"cd {CONTAINER_BUNDLE} && "
                )
            else:
                setup = (
                    f"mkdir -p {CONTAINER_WORKTREE} && "
                    f"tar -C {CONTAINER_REPOSITORY} "
                    "--exclude=.venv --exclude=out --exclude=.pytest_cache "
                    "--exclude=.ruff_cache -cf - . | "
                    f"tar -C {CONTAINER_WORKTREE} -xf - && "
                    f"cd {CONTAINER_WORKTREE} && "
                )
            result = workspace.execute_command(
                setup + command,
                cwd="/workspace",
                timeout=3600.0,
            )
            if result.exit_code == 0:
                for relative in download_files:
                    destination = repository / relative
                    file_result = workspace.file_download(
                        str(worktree / relative),
                        destination,
                    )
                    if not file_result.success:
                        raise RuntimeError(
                            f"failed to download workspace file {relative}: "
                            f"{file_result.error or 'unknown error'}"
                        )
                    downloaded.append(destination)
    finally:
        if previous_digest is None:
            os.environ.pop("ACD_CONTAINER_IMAGE_DIGEST", None)
        else:
            os.environ["ACD_CONTAINER_IMAGE_DIGEST"] = previous_digest
        if previous_marker is None:
            os.environ.pop("ACD_IN_CONTAINER", None)
        else:
            os.environ["ACD_IN_CONTAINER"] = previous_marker
    return WorkspaceResult(
        digest=reference.digest,
        source=reference.source,
        exit_code=result.exit_code,
        stdout=result.stdout,
        stderr=result.stderr,
        downloaded_files=tuple(downloaded),
    )


def run_command_in_local_workspace(
    *,
    command: str,
    repository: Path,
    workspace_factory: Callable[..., Any] | None = None,
) -> ProvisionalWorkspaceResult:
    """Run one command in a host-only LocalWorkspace as provisional output."""
    if "ACD_IN_CONTAINER" in os.environ or "ACD_CONTAINER_IMAGE_DIGEST" in os.environ:
        raise ValueError(
            "host provisional workspace refuses container provenance environment"
        )
    factory = workspace_factory or LocalWorkspace
    workspace = factory(working_dir=repository)
    with workspace:
        result = workspace.execute_command(
            command,
            cwd=repository,
            timeout=3600.0,
        )
    return ProvisionalWorkspaceResult(
        exit_code=result.exit_code,
        stdout=result.stdout,
        stderr=result.stderr,
    )
