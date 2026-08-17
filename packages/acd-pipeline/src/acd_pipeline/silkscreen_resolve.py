"""Measure and resolve GD1 silkscreen using the ACD projection boundary."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any, cast

from acd_adapter_kicad.cli import KicadCli
from acd_adapter_kicad.fab import (
    BoardMeasurement,
    build_silkscreen_context,
    parse_routed_board,
)
from acd_adapter_kicad.project import write_project
from acd_core.electrical import extract_electrical_lane
from acd_core.fab import extract_fab_intent, load_fab_profile
from acd_core.silkscreen import SilkscreenLane, extract_silkscreen_lane
from acd_schema.design_graph import DesignGraph

from .gd1_board import placements_from_graph
from .gd1_fixture.components import REPO_ROOT, sha256_of

SILK_SKILL = REPO_ROOT / (
    "plugins/acd/skills/acd-silkscreen-placement/scripts/silkscreen_search.py"
)
FAB_PROFILE = REPO_ROOT / "profiles/jlcpcb/fab-profile-jlcpcb-fr4-2l-1oz.json"


def measure_silkscreen(
    fixture_dir: Path,
    out_dir: Path,
    fab_profile_path: Path,
) -> dict[str, object]:
    """Project an unrouted board and return the gate-derived silk context.

    This is intentionally a routing-before-gate approximation: vias and their
    mask openings do not exist yet.  The routed GD1 pipeline remains the only
    acceptance gate and must be run after any candidate is written.
    """
    graph = DesignGraph.model_validate(
        json.loads((fixture_dir / "graph.json").read_text(encoding="utf-8"))
    )
    lane = extract_electrical_lane(graph)
    silkscreen = extract_silkscreen_lane(graph)
    intent, _allowances = extract_fab_intent(graph)
    profile = load_fab_profile(fab_profile_path)
    if intent.fab_profile != profile.profile_id:
        raise ValueError("graph fab profile differs from loaded profile")
    project = write_project(
        lane,
        fixture_dir,
        out_dir,
        profile=profile,
        placements=placements_from_graph(graph, lane),
        silkscreen=silkscreen,
    )
    kicad = KicadCli()
    layers = ["F.Mask", "B.Mask", "F.SilkS", "B.SilkS", "Edge.Cuts"]
    _run, paths = kicad.export_gerbers(project.board, out_dir / "gerbers", layers, graph.revision)
    by_layer = dict(zip(layers, paths, strict=True))
    measurement = parse_routed_board(project.board)
    measurement = BoardMeasurement(
        measurement.footprints,
        measurement.vias,
        measurement.min_track_width_mm,
        measurement.silk_min_height_mm,
        measurement.silk_min_width_mm,
        measurement.outline_bbox_mm,
        (),
        0,
        measurement.net_name_source,
        measurement.segments,
    )
    context = build_silkscreen_context(
        {"F.SilkS": by_layer["F.SilkS"], "B.SilkS": by_layer["B.SilkS"]},
        {"F.Mask": by_layer["F.Mask"], "B.Mask": by_layer["B.Mask"]},
        by_layer["Edge.Cuts"],
        measurement,
        silkscreen,
        profile,
    )
    result: dict[str, object] = {
        "fixture": str(fixture_dir),
        "board": str(project.board),
        "gerbers": {key: str(value) for key, value in by_layer.items()},
        "context": context,
        "approximation": (
            "unrouted projection; final routed-board gate remains authoritative "
            "because via mask openings are absent"
        ),
    }
    (out_dir / "silkscreen-context.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result


def resolve_silkscreen(
    fixture_dir: Path,
    out_dir: Path,
    fab_profile_path: Path = FAB_PROFILE,
    max_iterations: int = 3,
) -> dict[str, object]:
    """Run bounded projection/measurement/Skill iterations fail-closed."""
    if max_iterations <= 0:
        raise ValueError("max_iterations must be positive")
    work_fixture_dir = out_dir / "work-fixture"
    shutil.copytree(fixture_dir, work_fixture_dir, dirs_exist_ok=True)
    graph_path = work_fixture_dir / "graph.json"
    iterations: list[dict[str, object]] = []
    for iteration in range(1, max_iterations + 1):
        measured = measure_silkscreen(
            work_fixture_dir, out_dir / f"iteration-{iteration}", fab_profile_path
        )
        context_value = measured.get("context")
        if not isinstance(context_value, dict):
            raise ValueError("silkscreen context is malformed")
        context = cast(dict[str, Any], context_value)
        status = context.get("status")
        if status == "measured_pass":
            shutil.copy2(graph_path, fixture_dir / "graph.json")
            return {"status": "resolved", "iterations": iterations, "final": measured}
        graph = DesignGraph.model_validate(
            json.loads(graph_path.read_text(encoding="utf-8"))
        )
        lane = extract_silkscreen_lane(graph)
        with tempfile.TemporaryDirectory(prefix="acd-silk-context-") as directory:
            directory_path = Path(directory)
            input_path = directory_path / "input.json"
            output_path = directory_path / "output.json"
            input_path.write_text(
                json.dumps(
                    {"context": context, "lane": lane_to_json(lane)},
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            subprocess.run(
                [
                    sys.executable,
                    str(SILK_SKILL),
                    "--input",
                    str(input_path),
                    "--output",
                    str(output_path),
                ],
                check=True,
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
            )
            skill_result = cast(
                dict[str, Any], json.loads(output_path.read_text(encoding="utf-8"))
            )
        raw_candidates = skill_result.get("candidates")
        if not isinstance(raw_candidates, list):
            raise ValueError("silkscreen context Skill output is missing candidates")
        raw_candidates = cast(list[Any], raw_candidates)
        if not all(isinstance(item, dict) for item in raw_candidates):
            raise ValueError("silkscreen context Skill candidates are malformed")
        candidates = cast(list[dict[str, Any]], raw_candidates)
        accepted: dict[str, dict[str, Any]] = {
            str(item["node_id"]): item
            for item in candidates
            if item.get("accepted_position_mm") is not None
        }
        failures = [
            {
                "node_id": item.get("node_id"),
                "rejection_counts": _rejection_counts(item.get("rejected_candidates")),
                "rejected_candidates": item.get("rejected_candidates", []),
            }
            for item in candidates
            if item.get("accepted_position_mm") is None
        ]
        iterations.append(
            {
                "iteration": iteration,
                "context_status": status,
                "failure_reason": context.get("failure_reason"),
                "candidate_failures": failures,
            }
        )
        if failures or len(accepted) != len(lane.texts):
            return {
                "status": "failed_no_candidates",
                "iterations": iterations,
                "final": measured,
            }
        updated_nodes: list[Any] = []
        for node in graph.nodes:
            item = accepted.get(node.id)
            if node.kind == "mechanical.silk_text" and item is not None:
                attrs = dict(node.attrs)
                raw_position: Any = item["accepted_position_mm"]
                if not isinstance(raw_position, list):
                    raise ValueError("Skill candidate position is malformed")
                position_values = cast(list[Any], raw_position)
                if len(position_values) != 2 or not all(
                    isinstance(value, int | float) for value in position_values
                ):
                    raise ValueError("Skill candidate position is malformed")
                position = cast(list[float | int], position_values)
                attrs.update(
                    {
                        "x_mm": float(position[0]),
                        "y_mm": float(position[1]),
                        "rotation_deg": float(item["accepted_rotation_deg"]),
                        "placement_source": "acd-silkscreen-placement",
                        "placement_source_ref": (
                            "plugins/acd/skills/acd-silkscreen-placement/scripts/"
                            f"silkscreen_search.py:sha256:{sha256_of(SILK_SKILL)}"
                        ),
                        "placement_evidence": json.dumps(item, sort_keys=True),
                    }
                )
                updated_nodes.append(node.model_copy(update={"attrs": attrs}))
            else:
                updated_nodes.append(node)
        graph_path.write_text(
            json.dumps(
                graph.model_copy(update={"nodes": updated_nodes}).model_dump(mode="json"),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
    return {"status": "max_iterations_exceeded", "iterations": iterations}


def lane_to_json(lane: SilkscreenLane) -> dict[str, object]:
    return cast(dict[str, object], asdict(lane))


def _rejection_counts(value: Any) -> dict[str, int]:
    if not isinstance(value, list):
        return {"malformed": 1}
    counts: dict[str, int] = {}
    for item in cast(list[Any], value):
        reason = (
            str(cast(dict[str, Any], item).get("reason", "unknown"))
            if isinstance(item, dict)
            else "malformed"
        )
        counts[reason] = counts.get(reason, 0) + 1
    return dict(sorted(counts.items()))
