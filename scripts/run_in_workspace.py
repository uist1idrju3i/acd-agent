"""Run a deterministic ACD command in an OpenHands Docker workspace."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from acd.openhands.workspace import (
    DEFAULT_DOWNLOAD_FILES,
    ProvisionalWorkspaceResult,
    load_workspace_graph,
    run_command_in_local_workspace,
    run_command_in_workspace,
    workspace_defaults,
)


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
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if args.local_provisional and args.image:
        parser.error("--image cannot be used with --local-provisional")
    if args.local_provisional and args.source != "mounted":
        parser.error("--source cannot be used with --local-provisional")
    if not args.local_provisional and not args.image:
        parser.error("--image or ACD_CONTAINER_IMAGE is required")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv or sys.argv[1:])
    try:
        if args.command:
            command = " ".join(args.command).strip()
            download_files = tuple(args.download_files or DEFAULT_DOWNLOAD_FILES)
        else:
            graph_path = args.graph if args.graph.is_absolute() else args.repo / args.graph
            defaults = workspace_defaults(load_workspace_graph(graph_path).graph_id)
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
                source=args.source,
            )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if isinstance(result, ProvisionalWorkspaceResult):
        print("execution context: host (provisional)")
    else:
        print(f"image digest: {result.digest} ({result.source})")
    print(f"exit code: {result.exit_code}")
    print("stdout:")
    print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
    print("stderr:")
    print(result.stderr, end="" if result.stderr.endswith("\n") else "\n")
    if not isinstance(result, ProvisionalWorkspaceResult):
        for path in result.downloaded_files:
            print(f"downloaded: {path}")
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
