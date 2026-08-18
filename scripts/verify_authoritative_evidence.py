#!/usr/bin/env python3
"""Verify that every supplied Evidence record supports an authoritative pass."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import cast

from acd.schema.evidence import Evidence


def _revision_from_graph(path: Path) -> str:
    if not path.is_file():
        raise ValueError(f"revision graph not found: {path}")
    try:
        graph = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"could not parse revision graph {path}: {exc}") from exc
    graph_mapping = cast(dict[str, object], graph) if isinstance(graph, dict) else {}
    revision = graph_mapping.get("revision")
    if not isinstance(revision, str) or not revision:
        raise ValueError(f"revision graph has no non-empty revision: {path}")
    return revision


def _revision(value: str | None, revision_from: Path | None) -> str:
    if value is not None and revision_from is not None:
        raise ValueError("--revision and --revision-from are mutually exclusive")
    if value is not None:
        if not value:
            raise ValueError("revision must not be empty")
        return value
    if revision_from is not None:
        return _revision_from_graph(revision_from)
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    revision = result.stdout.strip()
    if result.returncode != 0 or not revision:
        raise ValueError("git revision could not be resolved")
    return revision


def verify(
    paths: Sequence[Path],
    revision: str | None = None,
    revision_from: Path | None = None,
) -> bool:
    """Return whether all supplied Evidence records support an authoritative pass."""
    if not paths:
        print("FAIL: no Evidence files supplied", file=sys.stderr)
        return False
    try:
        target_revision = _revision(revision, revision_from)
    except ValueError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return False
    for path in paths:
        if not path.is_file():
            print(f"FAIL: Evidence file not found: {path}", file=sys.stderr)
            return False
        try:
            evidence = Evidence.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"FAIL: could not parse Evidence {path}: {exc}", file=sys.stderr)
            return False
        if evidence.status != "valid":
            print(f"FAIL: {path}: status={evidence.status!r}", file=sys.stderr)
            return False
        if evidence.target_revision != target_revision:
            print(
                f"FAIL: {path}: revision mismatch "
                f"(target={evidence.target_revision!r}, current={target_revision!r})",
                file=sys.stderr,
            )
            return False
        if evidence.envelope.execution_context != "container":
            print(
                f"FAIL: {path}: execution_context="
                f"{evidence.envelope.execution_context!r}",
                file=sys.stderr,
            )
            return False
        digest = evidence.envelope.container_image_digest
        if digest is None or digest == "unknown":
            print(f"FAIL: {path}: container image digest is unknown", file=sys.stderr)
            return False
        if evidence.envelope.has_unknown():
            print(f"FAIL: {path}: envelope contains unknown values", file=sys.stderr)
            return False
        if not evidence.supports_authoritative_pass(target_revision):
            print(f"FAIL: {path}: authoritative pass is not supported", file=sys.stderr)
            return False
    print(f"OK: {len(paths)} authoritative Evidence file(s) verified")
    return True


def main(argv: Sequence[str] | None = None) -> int:
    """Parse arguments and verify authoritative Evidence files."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", help="expected git revision")
    parser.add_argument(
        "--revision-from",
        type=Path,
        help="read the expected revision from a design graph JSON file",
    )
    parser.add_argument("evidence", nargs="*", type=Path)
    args = parser.parse_args(argv)
    return 0 if verify(args.evidence, args.revision, args.revision_from) else 1


if __name__ == "__main__":
    raise SystemExit(main())
