"""Run a deterministic ACD command in an OpenHands Docker workspace."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from acd.openhands.container_runtime import (
    DEFAULT_COMMAND_TIMEOUT,
    DEFAULT_DOCKER_CLI_TIMEOUT,
    DEFAULT_FREEROUTING_MAX_HEAP,
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
    expected_source_revision,
    load_workspace_graph,
    run_command_in_local_workspace,
    run_command_in_workspace,
    workspace_defaults,
)
from acd.schema.host_resources import HostResourceReport

DEFAULT_GRAPH = Path("fixtures/golden-design-1/graph.json")
DEFAULT_BOOTSTRAP_RECORD = Path(".openhands/bootstrap-record.json")


def _prepare_cache_dir(cache_dir: Path) -> None:
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        return
    for path in (cache_dir, cache_dir / "uv", cache_dir / "ccache"):
        try:
            path.mkdir(exist_ok=True)
        except OSError:
            continue
        try:
            if not path.is_symlink():
                path.chmod(0o777)
        except OSError:
            continue
    for root, dirnames, filenames in os.walk(
        cache_dir,
        followlinks=False,
        onerror=lambda _error: None,
    ):
        root_path = Path(root)
        dirnames[:] = [
            name for name in dirnames if not (root_path / name).is_symlink()
        ]
        for name in dirnames:
            try:
                (root_path / name).chmod(0o777)
            except OSError:
                continue
        for name in filenames:
            path = root_path / name
            try:
                if path.is_symlink() or not path.is_file():
                    continue
                mode = path.stat().st_mode
                path.chmod(0o666 | (mode & 0o111))
            except OSError:
                continue


def _write_host_resource_report(
    path: Path | None, report: HostResourceReport | None
) -> None:
    if path is None or report is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")


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
        default=None,
        help=(
            "design graph used to derive default command and Evidence paths; "
            "an explicit --graph also supplies the default downloads for an "
            "explicit command, while a command without --graph downloads only "
            "the --download/--download-root paths (the default graph is used "
            "only when no command is given)"
        ),
    )
    parser.add_argument(
        "--download",
        dest="download_files",
        action="append",
        metavar="PATH",
        help="Evidence-relative file to download after a successful run.",
    )
    parser.add_argument(
        "--download-root",
        dest="download_roots",
        action="append",
        metavar="PATH",
        help=(
            "repository-relative output root whose *.json and *.log artifacts "
            "are downloaded after the run"
        ),
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
        "--jvm-max-heap",
        default=DEFAULT_FREEROUTING_MAX_HEAP,
        help="FreeRouting JVM maximum heap, for example '2g'.",
    )
    parser.add_argument(
        "--host-resource-report",
        type=Path,
        default=None,
        help="Write the host resource preflight report to this path.",
    )
    parser.add_argument(
        "--source-revision",
        default=None,
        metavar="SHA",
        help=(
            "expected source git sha; a mounted run whose source provenance "
            "deviates from it is refused before the container starts"
        ),
    )
    parser.add_argument(
        "--bootstrap-record",
        type=Path,
        default=None,
        metavar="PATH",
        help=(
            "bootstrap record JSON whose resolved_revision is the expected "
            "source sha (default: <repo>/.openhands/bootstrap-record.json "
            "when it exists)"
        ),
    )
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help=(
            "Allow an unresolvable (non-git) source tree or a source "
            "revision deviating from the bootstrap record: provenance is "
            "still recorded in the envelope, and the authoritative verifier "
            "rejects the produced Evidence (provisional only). A dirty "
            "source tree is always refused; this flag does not cover it."
        ),
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
    if args.local_provisional and args.host_resource_report:
        parser.error("--host-resource-report cannot be used with --local-provisional")
    if args.local_provisional and args.download_roots:
        parser.error("--download-root cannot be used with --local-provisional")
    if args.local_provisional and args.allow_dirty:
        parser.error("--allow-dirty cannot be used with --local-provisional")
    if args.local_provisional and args.source_revision:
        parser.error("--source-revision cannot be used with --local-provisional")
    if args.local_provisional and args.bootstrap_record:
        parser.error("--bootstrap-record cannot be used with --local-provisional")
    if not args.local_provisional and not args.image:
        parser.error("--image or ACD_CONTAINER_IMAGE is required")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv or sys.argv[1:])
    if args.cache_dir is not None:
        _prepare_cache_dir(args.cache_dir)
    try:
        if args.bootstrap_record is not None:
            if not args.bootstrap_record.is_file():
                raise ValueError(
                    f"bootstrap record not found: {args.bootstrap_record}"
                )
            bootstrap_record = args.bootstrap_record
        else:
            candidate = args.repo / DEFAULT_BOOTSTRAP_RECORD
            bootstrap_record = candidate if candidate.is_file() else None
        expected_revision = expected_source_revision(
            source_revision=args.source_revision,
            bootstrap_record=bootstrap_record,
        )
        # An explicit --graph with an explicit command keeps the historical
        # default downloads; a command without --graph downloads only what
        # --download/--download-root declared.
        graph_explicit = args.graph is not None
        defaults = None
        if not args.command or (
            graph_explicit and not (args.download_files or args.download_roots)
        ):
            graph = args.graph if graph_explicit else DEFAULT_GRAPH
            graph_path = graph if graph.is_absolute() else args.repo / graph
            defaults = workspace_defaults(
                load_workspace_graph(graph_path).graph_id, graph.parent
            )
        if args.command:
            command = " ".join(args.command).strip()
            download_files = tuple(
                args.download_files
                or (defaults.download_files if defaults is not None else ())
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
                download_roots=tuple(args.download_roots or ()),
                cache_dir=args.cache_dir,
                source=args.source,
                runtime=ContainerRuntimeConfig(
                    health_check_timeout=args.health_check_timeout,
                    command_timeout=args.command_timeout,
                    docker_cli_timeout=args.docker_cli_timeout,
                    memory_limit=args.memory_limit,
                    jvm_max_heap=args.jvm_max_heap,
                    platform=args.platform,
                ),
                allow_dirty=args.allow_dirty,
                expected_source_revision=expected_revision,
            )
    except WorkspaceStartupError as exc:
        _write_host_resource_report(args.host_resource_report, exc.host_resource_report)
        if exc.host_resource_report is not None:
            for finding in exc.host_resource_report.findings:
                print(f"{finding.code}: {finding.detail}", file=sys.stderr)
        print(f"workspace failure ({exc.failure_kind}): {exc}", file=sys.stderr)
        return 2
    except WorkspaceTransportError as exc:
        print(f"exit code: {exc.exit_code}")
        print("stdout:")
        print(exc.stdout, end="" if exc.stdout.endswith("\n") else "\n")
        print("stderr:")
        print(exc.stderr, end="" if exc.stderr.endswith("\n") else "\n")
        for path in exc.downloaded_files:
            print(f"downloaded: {path}")
        print(f"workspace failure ({exc.failure_kind}): {exc}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if isinstance(result, ProvisionalWorkspaceResult):
        print("execution context: host (provisional)")
    else:
        print(f"image digest: {result.digest} ({result.source})")
        print(
            f"source provenance: {result.source_revision} "
            f"{result.source_tree_state}"
        )
        if expected_revision is not None:
            origins: list[str] = []
            if args.source_revision is not None:
                origins.append("--source-revision")
            if bootstrap_record is not None:
                origins.append(f"bootstrap record {bootstrap_record}")
            print(
                f"expected source revision: {expected_revision} "
                f"({' + '.join(origins)})"
            )
    _write_host_resource_report(
        args.host_resource_report,
        (
            None
            if isinstance(result, ProvisionalWorkspaceResult)
            else result.host_resource_report
        ),
    )
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
        for error in result.download_errors:
            print(f"download not retrieved: {error}", file=sys.stderr)
        if result.failure_kind is not None:
            print(f"failure kind: {result.failure_kind}", file=sys.stderr)
            return result.exit_code if result.exit_code > 0 else 2
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
