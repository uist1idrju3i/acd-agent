"""Run deterministic ACD commands through a digest-pinned server workspace."""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

from openhands.sdk.workspace import LocalWorkspace
from openhands.workspace import DockerWorkspace

from acd.core.naming import artifact_prefix, required_evidence_ids
from acd.openhands.container_runtime import (
    ContainerRuntimeConfig,
    FailureKind,
    docker_cli_bounds,
    startup_failure_kind,
    stop_containers,
)
from acd.openhands.host_resources import (
    ResourceRequirement,
    check_host_resources,
    parse_memory_bytes,
)
from acd.schema.design_graph import DesignGraph
from acd.schema.host_resources import HostResourceReport

CONTAINER_REPOSITORY = Path("/acd-src")
HOST_OUT_ROOT = Path("out")
CONTAINER_OUT_ROOT = Path("out/container")
CONTAINER_WORKTREE = Path("/workspace/acd")
CONTAINER_BUNDLE = Path("/opt/acd")
_DIGEST = re.compile(r"sha256:[0-9a-fA-F]{64}\Z")
DOCKER_INSPECT_TIMEOUT = 60.0
DOWNLOAD_MAX_ATTEMPTS = 3
DOWNLOAD_BACKOFF_SECONDS = 0.5

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


def container_download_destination(repository: Path, relative: str) -> Path:
    """Map a container output path into the host container-execution out root.

    Container and host executions never share one output root: container results
    are downloaded under ``out/container/`` so a host run cannot overwrite them
    and a root-owned container artifact cannot make a host run fail with a
    permission error that looks like a design rejection.
    """
    path = Path(relative)
    if path.is_absolute():
        raise ValueError(f"download path must be repository-relative: {relative}")
    if path.parts[:1] == (HOST_OUT_ROOT.name,):
        return repository / CONTAINER_OUT_ROOT / Path(*path.parts[1:])
    return repository / path


@dataclass(frozen=True)
class WorkspaceResult:
    digest: str
    source: str
    exit_code: int
    stdout: str
    stderr: str
    downloaded_files: tuple[Path, ...]
    failure_kind: FailureKind | None = None
    host_resource_report: HostResourceReport | None = None


class WorkspaceStartupError(RuntimeError):
    """A digest-pinned workspace could not be started."""

    def __init__(
        self,
        message: str,
        *,
        failure_kind: FailureKind,
        host_resource_report: HostResourceReport | None = None,
    ) -> None:
        super().__init__(message)
        self.failure_kind = failure_kind
        self.host_resource_report = host_resource_report


class WorkspaceTransportError(RuntimeError):
    """A workspace file transfer failed after its bounded retries."""

    failure_kind: FailureKind = "transport"


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
    timeout: float,
) -> subprocess.CompletedProcess[str]:
    return run(
        ["docker", "image", "inspect", f"--format={format_string}", image],
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )


def resolve_image_digest(
    image: str,
    *,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    timeout: float = DOCKER_INSPECT_TIMEOUT,
) -> ImageReference | None:
    """Resolve a content address for an image, or return ``None``.

    Every docker CLI call is bounded by ``timeout``; an inspect call that
    exceeds it is treated as unresolved so callers stay fail-closed.
    """
    try:
        repo_digests = _inspect(
            image, format_string="{{json .RepoDigests}}", run=run, timeout=timeout
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
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
        image_id = _inspect(
            image, format_string="{{.Id}}", run=run, timeout=timeout
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    candidate = image_id.stdout.strip()
    if image_id.returncode == 0 and _DIGEST.fullmatch(candidate):
        return ImageReference(candidate, "image ID")
    return None


def _download_with_retry(
    workspace: Any,
    *,
    remote: str,
    destination: Path,
    relative: str,
    max_attempts: int,
    backoff_seconds: float,
    sleep: Callable[[float], None],
) -> None:
    """Download one evidence file, retrying the transfer a bounded number of times."""
    error = "unknown error"
    for attempt in range(1, max_attempts + 1):
        file_result = workspace.file_download(remote, destination)
        if file_result.success:
            return
        error = file_result.error or "unknown error"
        if attempt < max_attempts:
            sleep(backoff_seconds * attempt)
    raise WorkspaceTransportError(
        f"failed to download workspace file {relative} after {max_attempts} "
        f"attempts: {error}"
    )


def _command_failure_kind(exit_code: int, timeout_occurred: bool) -> FailureKind | None:
    if timeout_occurred:
        return "timeout"
    if exit_code == -1:
        return "transport"
    if exit_code != 0:
        return "command"
    return None


def run_command_in_workspace(
    *,
    image: str,
    command: str,
    repository: Path,
    download_files: tuple[str, ...],
    cache_dir: Path | None = None,
    workspace_factory: Callable[..., Any] | None = None,
    source: WorkspaceSource = "mounted",
    runtime: ContainerRuntimeConfig | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> WorkspaceResult:
    """Run one command in a DockerWorkspace using a resolved server digest.

    With ``source="mounted"`` the host repository is mounted read-only and
    copied into the container worktree. With ``source="bundled"`` the ACD
    source, pipeline scripts, fixtures, and contracts baked into the locked
    image are used and no repository is mounted; a missing or incomplete bundle
    stops the run.

    ``runtime`` declares the container bounds explicitly: health check timeout,
    platform, log streaming, memory limit, docker CLI timeout, and command
    timeout. Startup failures stop the containers that were created and raise
    ``WorkspaceStartupError`` with the observed failure kind.
    """
    if not image.strip():
        raise ValueError("server image must not be empty")
    if source not in ("mounted", "bundled"):
        raise ValueError(f"unknown workspace source: {source!r}")
    config = runtime or ContainerRuntimeConfig()
    host_resource_report = check_host_resources(
        ResourceRequirement(
            memory_limit_bytes=parse_memory_bytes(config.memory_limit),
            jvm_max_heap_bytes=parse_memory_bytes(config.jvm_max_heap),
        ),
        disk_path=repository,
        declared_jvm_max_heap=config.jvm_max_heap,
    )
    if host_resource_report.status != "pass":
        findings = "; ".join(
            f"{finding.code}: {finding.detail}"
            for finding in host_resource_report.findings
        )
        raise WorkspaceStartupError(
            f"host resource preflight failed: {findings}",
            failure_kind="resources",
            host_resource_report=host_resource_report,
        )
    reference = resolve_image_digest(image, timeout=config.docker_cli_timeout)
    if reference is None:
        raise ValueError("server image digest could not be resolved; refusing to execute")

    factory = workspace_factory or DockerWorkspace
    previous_digest = os.environ.get("ACD_CONTAINER_IMAGE_DIGEST")
    previous_marker = os.environ.get("ACD_IN_CONTAINER")
    cache_environment = {
        "UV_CACHE_DIR": "/opt/acd-cache/uv",
        "CCACHE_DIR": "/opt/acd-cache/ccache",
    }
    previous_cache_environment = {
        name: os.environ.get(name) for name in cache_environment
    }
    os.environ["ACD_CONTAINER_IMAGE_DIGEST"] = reference.digest
    os.environ["ACD_IN_CONTAINER"] = "1"
    if cache_dir is not None:
        for name, value in cache_environment.items():
            os.environ[name] = value
    downloaded: list[Path] = []
    worktree = CONTAINER_BUNDLE if source == "bundled" else CONTAINER_WORKTREE
    try:
        constructor_kwargs: dict[str, Any] = {
            "server_image": image,
            "forward_env": ["ACD_CONTAINER_IMAGE_DIGEST", "ACD_IN_CONTAINER"],
            **config.workspace_kwargs(),
        }
        volumes: list[str] = []
        if source == "mounted":
            volumes.append(f"{repository.resolve()}:{CONTAINER_REPOSITORY}:ro")
        if cache_dir is not None:
            volumes.append(f"{cache_dir.resolve()}:/opt/acd-cache")
            constructor_kwargs["forward_env"] = [
                *constructor_kwargs["forward_env"],
                *cache_environment,
            ]
        if volumes:
            constructor_kwargs["volumes"] = volumes
        with docker_cli_bounds(config) as observations:
            try:
                workspace = factory(**constructor_kwargs)
            except (RuntimeError, ValueError, OSError) as exc:
                unstopped = stop_containers(
                    observations.container_ids, timeout=config.docker_cli_timeout
                )
                kind = startup_failure_kind(exc, observations)
                detail = (
                    f"; containers still running: {', '.join(unstopped)}"
                    if unstopped
                    else ""
                )
                raise WorkspaceStartupError(
                    f"workspace could not be started: {exc}{detail}",
                    failure_kind=kind,
                ) from exc
            result = _execute_and_download(
                workspace,
                command=command,
                source=source,
                worktree=worktree,
                repository=repository,
                download_files=download_files,
                downloaded=downloaded,
                config=config,
                sleep=sleep,
            )
    finally:
        if previous_digest is None:
            os.environ.pop("ACD_CONTAINER_IMAGE_DIGEST", None)
        else:
            os.environ["ACD_CONTAINER_IMAGE_DIGEST"] = previous_digest
        if previous_marker is None:
            os.environ.pop("ACD_IN_CONTAINER", None)
        else:
            os.environ["ACD_IN_CONTAINER"] = previous_marker
        for name, previous in previous_cache_environment.items():
            if previous is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = previous
    return WorkspaceResult(
        digest=reference.digest,
        source=reference.source,
        exit_code=result.exit_code,
        stdout=result.stdout,
        stderr=result.stderr,
        downloaded_files=tuple(downloaded),
        failure_kind=_command_failure_kind(
            result.exit_code, bool(result.timeout_occurred)
        ),
        host_resource_report=host_resource_report,
    )


def _execute_and_download(
    workspace: Any,
    *,
    command: str,
    source: WorkspaceSource,
    worktree: Path,
    repository: Path,
    download_files: tuple[str, ...],
    downloaded: list[Path],
    config: ContainerRuntimeConfig,
    sleep: Callable[[float], None],
) -> Any:
    with workspace:
        if source == "bundled":
            setup = (
                f"test -f {CONTAINER_BUNDLE / 'pyproject.toml'} && "
                f"test -f {CONTAINER_BUNDLE / 'uv.lock'} && "
                f"test -d {CONTAINER_BUNDLE / 'src' / 'acd'} && "
                f"test -d {CONTAINER_BUNDLE / 'scripts'} && "
                f"test -d {CONTAINER_BUNDLE / 'fixtures'} && "
                f"test -d {CONTAINER_BUNDLE / 'contracts'} && "
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
            timeout=config.command_timeout,
        )
        if result.exit_code == 0:
            for relative in download_files:
                destination = container_download_destination(repository, relative)
                destination.parent.mkdir(parents=True, exist_ok=True)
                _download_with_retry(
                    workspace,
                    remote=str(worktree / relative),
                    destination=destination,
                    relative=relative,
                    max_attempts=DOWNLOAD_MAX_ATTEMPTS,
                    backoff_seconds=DOWNLOAD_BACKOFF_SECONDS,
                    sleep=sleep,
                )
                downloaded.append(destination)
    return result


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
