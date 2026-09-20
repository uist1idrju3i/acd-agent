"""Derive an L3 graph projection from a declared rework difference."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from acd.core.manufacturing.rework_diff import (
    ReworkDiffError,
    apply_rework_diff,
    load_rework_diff,
    write_derived_graph,
)
from acd.schema.design_graph import DesignGraph


def _load_graph(path: Path) -> DesignGraph:
    try:
        return DesignGraph.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ReworkDiffError(f"design graph is invalid: {path}: {exc}") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Derive a design graph from a rework difference."
    )
    parser.add_argument("--graph", type=Path, required=True)
    parser.add_argument("--rework", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        graph = _load_graph(args.graph)
        loaded = load_rework_diff(args.rework)
        derived = apply_rework_diff(graph, loaded.diff, graph_path=args.graph)
        output_path = write_derived_graph(derived, args.out_dir)
    except ReworkDiffError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "artifact": str(output_path),
                "derived_revision": derived.derived_revision,
                "safety_boundary_touched": derived.safety_boundary_touched,
                "touched_node_ids": list(derived.touched_node_ids),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
