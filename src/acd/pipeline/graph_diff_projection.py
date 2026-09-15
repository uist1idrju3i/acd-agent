"""Pipeline entry point for the graph difference visual projection."""

from __future__ import annotations

import json
import os
from pathlib import Path

from acd.adapters.svg.graph_diff import generate_graph_diff_visual_projection
from acd.core.fileio import read_json
from acd.schema.design_graph import DesignGraph


class GraphDiffProjectionError(ValueError):
    """Raised when graph-diff projection inputs or output are invalid."""


def _load_graph(path: Path) -> DesignGraph:
    try:
        payload = read_json(path)
        return DesignGraph.model_validate(payload)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise GraphDiffProjectionError(
            f"graph could not be loaded: {path}: {exc}"
        ) from exc


def run_graph_diff_projection(
    *,
    graph_path: Path,
    previous_graph_path: Path,
    out_dir: Path,
    project_name: str,
) -> Path:
    current = _load_graph(graph_path)
    previous = _load_graph(previous_graph_path)
    try:
        input_base_dir = Path(
            os.path.commonpath(
                [graph_path.resolve(), previous_graph_path.resolve()]
            )
        )
    except ValueError as exc:
        raise GraphDiffProjectionError(
            f"graph diff projection input base directory could not be determined: {exc}"
        ) from exc
    try:
        generate_graph_diff_visual_projection(
            project_name=project_name,
            out_dir=out_dir,
            previous_graph=previous,
            current_graph=current,
            authoritative_inputs=(previous_graph_path, graph_path),
            input_base_dir=input_base_dir,
        )
    except (OSError, ValueError) as exc:
        raise GraphDiffProjectionError(
            f"graph diff projection could not be generated: {out_dir}: {exc}"
        ) from exc
    return out_dir / "visual-projections-graph-diff.json"


__all__ = ["GraphDiffProjectionError", "run_graph_diff_projection"]
