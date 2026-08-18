"""Measure and resolve GD1 silkscreen using the ACD projection boundary."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any, cast

from acd.adapters.kicad.cli import KicadCli
from acd.adapters.kicad.fab import (
    BoardMeasurement,
    build_silkscreen_context,
    parse_routed_board,
)
from acd.adapters.kicad.project import write_project
from acd.core.electrical import BoardView, extract_electrical_lane
from acd.core.fab import extract_fab_intent, load_fab_profile
from acd.core.silkscreen import SilkscreenLane, extract_silkscreen_lane
from acd.schema.design_graph import DesignGraph

from .gd1_board import placements_from_graph
from .gd1_fixture.components import sha256_of
from .placement_evidence import summarize_placement_evidence
from .repository import repository_root, resolve_repository_file


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
    projection_silkscreen = _materialize_unresolved_texts(silkscreen, lane.board)
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
        silkscreen=projection_silkscreen,
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
    resolved_source_paths = {
        graphic.node_id: resolve_repository_file(graphic.source_path)
        for graphic in projection_silkscreen.graphics
        if graphic.source_path is not None
    }
    context = build_silkscreen_context(
        {"F.SilkS": by_layer["F.SilkS"], "B.SilkS": by_layer["B.SilkS"]},
        {"F.Mask": by_layer["F.Mask"], "B.Mask": by_layer["B.Mask"]},
        by_layer["Edge.Cuts"],
        measurement,
        projection_silkscreen,
        profile,
        resolved_source_paths,
    )
    _restore_unresolved_positions(context, silkscreen)
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


def _restore_unresolved_positions(
    context: dict[str, object],
    declarations: SilkscreenLane,
) -> None:
    raw_value = context.get("declarations")
    if not isinstance(raw_value, list):
        return
    raw_declarations = cast(list[dict[str, object]], raw_value)
    unresolved = {
        text.node_id
        for text in declarations.texts
        if text.x_mm is None or text.y_mm is None
    }
    for item in raw_declarations:
        if item.get("node_id") in unresolved:
            item["declared_position_mm"] = None


def _materialize_unresolved_texts(
    lane: SilkscreenLane,
    board: BoardView,
) -> SilkscreenLane:
    provisional_x = float(board.width_mm) / 2.0
    provisional_y = float(board.height_mm) / 2.0
    texts = tuple(
        replace(
            text,
            x_mm=provisional_x if text.x_mm is None else text.x_mm,
            y_mm=provisional_y if text.y_mm is None else text.y_mm,
        )
        for text in lane.texts
    )
    return SilkscreenLane(
        board_node_id=lane.board_node_id,
        texts=texts,
        graphics=lane.graphics,
        placement_evidence=lane.placement_evidence,
    )


def _assert_no_unresolved_texts(lane: SilkscreenLane) -> None:
    unresolved = [
        text.node_id
        for text in lane.texts
        if text.x_mm is None or text.y_mm is None
    ]
    if unresolved:
        raise ValueError(
            "silkscreen resolution accepted unresolved text coordinates: "
            + ", ".join(unresolved)
        )


def resolve_silkscreen(
    fixture_dir: Path,
    out_dir: Path,
    fab_profile_path: Path | None = None,
    max_iterations: int = 5,
) -> dict[str, object]:
    """Run bounded projection/measurement/Skill iterations fail-closed."""
    if max_iterations <= 0:
        raise ValueError("max_iterations must be positive")
    root = repository_root()
    silk_skill = root / "plugins/acd/skills/acd-silkscreen-placement/scripts/silkscreen_search.py"
    if fab_profile_path is None:
        fab_profile_path = root / "profiles/jlcpcb/fab-profile-jlcpcb-fr4-2l-1oz.json"
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
            final_graph = DesignGraph.model_validate(
                json.loads(graph_path.read_text(encoding="utf-8"))
            )
            _assert_no_unresolved_texts(extract_silkscreen_lane(final_graph))
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
                    str(silk_skill),
                    "--input",
                    str(input_path),
                    "--output",
                    str(output_path),
                ],
                check=True,
                cwd=root,
                capture_output=True,
                text=True,
            )
            skill_result = cast(
                dict[str, Any], json.loads(output_path.read_text(encoding="utf-8"))
            )
            skill_input_sha256 = sha256_of(input_path)
        full_evidence_path = (
            out_dir / f"iteration-{iteration}" / "silkscreen-skill-result.json"
        )
        full_evidence_path.write_text(
            json.dumps(skill_result, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
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
        failures: list[dict[str, object]] = [
            {
                "node_id": item.get("node_id"),
                "rejection_counts": _rejection_counts(item.get("rejected_candidates")),
                "rejection_examples": (
                    cast(list[object], item.get("rejected_candidates", []))[:5]
                    if isinstance(item.get("rejected_candidates"), list)
                    else []
                ),
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
                evidence_summary = summarize_placement_evidence(item)
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
                        "placement_rotation_deg": float(
                            item["accepted_rotation_deg"]
                        ),
                        "placement_source": "acd-silkscreen-placement",
                        "placement_source_ref": (
                            "plugins/acd/skills/acd-silkscreen-placement/scripts/"
                            f"silkscreen_search.py:{sha256_of(silk_skill)}"
                        ),
                        "placement_evidence": json.dumps(
                            evidence_summary, ensure_ascii=False, sort_keys=True
                        ),
                        "placement_evidence_input_sha256": skill_input_sha256,
                        "placement_evidence_output_sha256": sha256_of(
                            full_evidence_path
                        ),
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
