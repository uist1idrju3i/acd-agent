"""Run a deterministic ACD command in an OpenHands Docker workspace."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from contextlib import suppress
from pathlib import Path

from acd.openhands.container_runtime import (
    DEFAULT_COMMAND_TIMEOUT,
    DEFAULT_DOCKER_CLI_TIMEOUT,
    DEFAULT_HEALTH_CHECK_TIMEOUT,
    DEFAULT_MEMORY_LIMIT,
    DEFAULT_PLATFORM,
    ContainerRuntimeConfig,
)
from acd.openhands.execution_failure import classify_execution_failure
from acd.openhands.workspace import (
    ProvisionalWorkspaceResult,
    WorkspaceStartupError,
    WorkspaceTransportError,
    load_workspace_graph,
    run_command_in_local_workspace,
    run_command_in_workspace,
    workspace_defaults,
)


def _prepare_cache_dir(cache_dir: Path) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    for path in (cache_dir, cache_dir / "uv", cache_dir / "ccache"):
        path.mkdir(exist_ok=True)
    for path in cache_dir.rglob("*"):
        if path.is_dir() and not path.is_symlink():
            with suppress(PermissionError):
                path.chmod(0o777)


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--image",
        default=os.getenv("ACD_CONTAINER_IMAGE"),
        help="Docker image reference (or set ACD_CONTAINER_IMAGE).",
    )
    parser.add_argument(
        "--local-provisional",
        action="store_true",
        help="Run through SDK LocalWorkspace as host-only provisional output.",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=None,
        help="opt-in host directory for forwarded uv and ccache caches",
    )
    parser.add_argument(
        "--source",
        choices=("mounted", "bundled"),
        default="mounted",
        help="Use the mounted repository or the ACD bundle baked into the image.",
    )
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument(
        "--graph",
        type=Path,
        default=Path("fixtures/golden-design-1/graph.json"),
        help="design graph used to derive default command and Evidence paths",
    )
    parser.add_argument(
        "--download",
        dest="download_files",
        action="append",
        metavar="PATH",
        help="Evidence-relative file to download after a successful run.",
    )
    parser.add_argument(
        "--health-check-timeout",
        type=float,
        default=DEFAULT_HEALTH_CHECK_TIMEOUT,
        help="Seconds to wait for the container health check.",
    )
    parser.add_argument(
        "--command-timeout",
        type=float,
        default=DEFAULT_COMMAND_TIMEOUT,
        help="Seconds allowed for the in-container command.",
    )
    parser.add_argument(
        "--docker-cli-timeout",
        type=float,
        default=DEFAULT_DOCKER_CLI_TIMEOUT,
        help="Seconds allowed for each docker CLI call.",
    )
    parser.add_argument(
        "--memory-limit",
        default=DEFAULT_MEMORY_LIMIT,
        help="Container memory limit, for example '8g'.",
    )
    parser.add_argument(
        "--platform",
        default=DEFAULT_PLATFORM,
        help="Explicit docker platform for the container.",
    )
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if args.local_provisional and args.image:
        parser.error("--image cannot be used with --local-provisional")
    if args.local_provisional and args.source != "mounted":
        parser.error("--source cannot be used with --local-provisional")
    if args.local_provisional and args.cache_dir:
        parser.error("--cache-dir cannot be used with --local-provisional")
    if not args.local_provisional and not args.image:
        parser.error("--image or ACD_CONTAINER_IMAGE is required")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv or sys.argv[1:])
    if args.cache_dir is not None:
        _prepare_cache_dir(args.cache_dir)
    try:
        defaults = None
        if not args.download_files or not args.command:
            graph_path = args.graph if args.graph.is_absolute() else args.repo / args.graph
            defaults = workspace_defaults(load_workspace_graph(graph_path).graph_id)
        if args.command:
            command = " ".join(args.command).strip()
            if args.download_files:
                download_files = tuple(args.download_files)
            elif defaults is not None:
                download_files = defaults.download_files
            else:
                raise ValueError(
                    "download files must be explicit when the design graph is unknown"
                )
        else:
            if defaults is None:
                raise ValueError(
                    "workspace defaults could not be derived from the design graph"
                )
            command = defaults.command
            download_files = tuple(args.download_files or defaults.download_files)
        if args.local_provisional:
            result = run_command_in_local_workspace(
                command=command,
                repository=args.repo,
            )
        else:
            result = run_command_in_workspace(
                image=args.image,
                command=command,
                repository=args.repo,
                download_files=download_files,
                cache_dir=args.cache_dir,
                source=args.source,
                runtime=ContainerRuntimeConfig(
                    health_check_timeout=args.health_check_timeout,
                    command_timeout=args.command_timeout,
                    docker_cli_timeout=args.docker_cli_timeout,
                    memory_limit=args.memory_limit,
                    platform=args.platform,
                ),
            )
    except (WorkspaceStartupError, WorkspaceTransportError) as exc:
        print(f"workspace failure ({exc.failure_kind}): {exc}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if isinstance(result, ProvisionalWorkspaceResult):
        print("execution context: host (provisional)")
    else:
        print(f"image digest: {result.digest} ({result.source})")
    print(f"exit code: {result.exit_code}")
    classification = classify_execution_failure(
        result.exit_code, f"{result.stdout}\n{result.stderr}"
    )
    if classification != "none":
        print(f"failure classification: {classification}")
    print("stdout:")
    print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
    print("stderr:")
    print(result.stderr, end="" if result.stderr.endswith("\n") else "\n")
    if not isinstance(result, ProvisionalWorkspaceResult):
        for path in result.downloaded_files:
            print(f"downloaded: {path}")
        if result.failure_kind is not None:
            print(f"failure kind: {result.failure_kind}", file=sys.stderr)
            return result.exit_code if result.exit_code > 0 else 2
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
