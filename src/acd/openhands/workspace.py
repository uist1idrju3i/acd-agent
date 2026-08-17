"""Run deterministic ACD commands through the OpenHands workspace API."""

from __future__ import annotations

import json
import os
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from openhands.workspace.docker import DockerDevWorkspace

DEFAULT_COMMAND = (
    "uv run python scripts/run_gd1_enclosure_pipeline.py "
    "--out out/gd1-enclosure"
)
_DIGEST = re.compile(r"sha256:[0-9a-fA-F]{64}\Z")


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


def _workspace_factory() -> type[Any]:
    return DockerDevWorkspace


def run_command_in_workspace(
    *,
    image: str,
    command: str,
    repository: Path,
    workspace_factory: Callable[..., Any] | None = None,
) -> WorkspaceResult:
    """Run one command in a DockerDevWorkspace."""
    reference = resolve_image_digest(image)
    if reference is None:
        raise ValueError("image digest could not be resolved; refusing to execute")

    factory = workspace_factory or _workspace_factory()
    previous_digest = os.environ.get("ACD_CONTAINER_IMAGE_DIGEST")
    previous_marker = os.environ.get("ACD_IN_CONTAINER")
    os.environ["ACD_CONTAINER_IMAGE_DIGEST"] = reference.digest
    os.environ["ACD_IN_CONTAINER"] = "1"
    try:
        workspace = factory(
            base_image=image,
            volumes=[f"{repository.resolve()}:/workspace"],
            forward_env=["ACD_CONTAINER_IMAGE_DIGEST", "ACD_IN_CONTAINER"],
        )
        with workspace:
            result = workspace.execute_command(command, cwd="/workspace")
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
    )
