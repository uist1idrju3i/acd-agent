"""Run a deterministic ACD command in an OpenHands Docker workspace."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

DEFAULT_COMMAND = (
    "uv run python scripts/run_gd1_enclosure_pipeline.py "
    "--out out/gd1-enclosure"
)
_DIGEST = re.compile(r"sha256:[0-9a-fA-F]{64}\Z")


@dataclass(frozen=True)
class ImageReference:
    digest: str
    source: str


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
    from openhands.workspace.docker import DockerDevWorkspace

    return DockerDevWorkspace


def run_command_in_workspace(
    *,
    image: str,
    command: str,
    repository: Path,
    workspace_factory: Callable[..., Any] | None = None,
) -> int:
    """Run one command in a DockerDevWorkspace and print its result."""
    reference = resolve_image_digest(image)
    if reference is None:
        print("image digest could not be resolved; refusing to execute", file=sys.stderr)
        return 2

    factory = workspace_factory or _workspace_factory()
    previous_digest = os.environ.get("ACD_CONTAINER_IMAGE_DIGEST")
    os.environ["ACD_CONTAINER_IMAGE_DIGEST"] = reference.digest
    try:
        workspace = factory(
            base_image=image,
            volumes=[f"{repository.resolve()}:/workspace"],
            forward_env=["ACD_CONTAINER_IMAGE_DIGEST"],
        )
        with workspace:
            result = workspace.execute_command(command, cwd="/workspace")
    finally:
        if previous_digest is None:
            os.environ.pop("ACD_CONTAINER_IMAGE_DIGEST", None)
        else:
            os.environ["ACD_CONTAINER_IMAGE_DIGEST"] = previous_digest

    print(f"image digest: {reference.digest} ({reference.source})")
    print(f"exit code: {result.exit_code}")
    print("stdout:")
    print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
    print("stderr:")
    print(result.stderr, end="" if result.stderr.endswith("\n") else "\n")
    for relative in ("out", "evidence"):
        path = repository / relative
        if path.exists():
            print(f"generated {relative}: {path}")
    return result.exit_code


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--image",
        default=os.getenv("ACD_CONTAINER_IMAGE"),
        help="Docker image reference (or set ACD_CONTAINER_IMAGE).",
    )
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if not args.image:
        parser.error("--image or ACD_CONTAINER_IMAGE is required")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv or sys.argv[1:])
    command = " ".join(args.command).strip() or DEFAULT_COMMAND
    return run_command_in_workspace(
        image=args.image,
        command=command,
        repository=args.repo,
    )


if __name__ == "__main__":
    raise SystemExit(main())
