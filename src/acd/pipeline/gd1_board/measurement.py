"""Post-fabrication measurements: silkscreen, net widths, pad centers, ground planes."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import cast

from acd.adapters.kicad.cli import KicadCli, RuleCheckResult
from acd.adapters.kicad.fab import (
    BoardMeasurement,
    measure_net_path_resistance,
    measure_net_track_widths,
    measure_silkscreen,  # pyright: ignore[reportUnknownVariableType]
    parse_routed_board,
    read_drill_measurement,
    verify_ground_plane_gerbers,
    verify_smd_pad_centers_in_gerber,
)
from acd.adapters.kicad.project import ProjectFiles
from acd.core.board_model import RoutedDesign
from acd.core.electrical import ElectricalLane
from acd.core.fab import FabProfile
from acd.core.parallel import run_ordered_stages
from acd.core.routing_width import derive_net_widths
from acd.core.silkscreen import SilkscreenLane
from acd.pipeline.repository import resolve_repository_file
from acd.pipeline.stitch_candidate_evidence import summarize_stitch_candidate_report

from .width_control import measure_dsn_class_correspondence

GERBER_LAYERS = [
    "F.Cu",
    "B.Cu",
    "F.Mask",
    "B.Mask",
    "F.SilkS",
    "B.SilkS",
    "F.Paste",
    "Edge.Cuts",
]


@dataclass(frozen=True)
class BoardMeasurements:
    measurement: BoardMeasurement
    drill_count: int
    silk_evidence: dict[str, object]
    width_evidence: dict[str, object]
    plane_measurement: dict[str, object]


def measure_board(
    *,
    project: ProjectFiles,
    lane: ElectricalLane,
    silkscreen: SilkscreenLane,
    profile: FabProfile,
    kicad: KicadCli,
    drc: RuleCheckResult,
    kicad_positive_control: dict[str, object],
    routed_path: Path,
    dsn_path: Path,
    gerber_paths: Sequence[Path],
    drill_paths: Sequence[Path],
    routes: RoutedDesign,
    stitch_vias: tuple[tuple[float, float], ...],
    initial_stitch_report: dict[str, object],
    pipeline_workers: int,
) -> BoardMeasurements:
    """Measure the exported fabrication outputs independently of KiCad's own reports."""
    measurement = parse_routed_board(routed_path)
    drill_tools, drill_count = read_drill_measurement(drill_paths[0])
    measurement = BoardMeasurement(
        measurement.footprints,
        measurement.vias,
        measurement.min_track_width_mm,
        measurement.silk_min_height_mm,
        measurement.silk_min_width_mm,
        measurement.outline_bbox_mm,
        drill_tools,
        drill_count,
        measurement.net_name_source,
        measurement.segments,
    )
    profile_minimum = float(profile.data["capabilities"]["min_track_width"]["value"])
    width_requirements = derive_net_widths(lane, profile_minimum)
    if lane.board.width_measurement_tolerance_mm is None:
        raise ValueError("width measurement tolerance is missing (fail-closed)")
    measurement_stages = run_ordered_stages(
        (
            (
                "silkscreen",
                partial(
                    measure_silkscreen,
                    {
                        "F.SilkS": gerber_paths[GERBER_LAYERS.index("F.SilkS")],
                        "B.SilkS": gerber_paths[GERBER_LAYERS.index("B.SilkS")],
                    },
                    {
                        "F.Mask": gerber_paths[GERBER_LAYERS.index("F.Mask")],
                        "B.Mask": gerber_paths[GERBER_LAYERS.index("B.Mask")],
                    },
                    gerber_paths[GERBER_LAYERS.index("Edge.Cuts")],
                    measurement,
                    silkscreen,
                    profile,
                    {
                        graphic.node_id: resolve_repository_file(graphic.source_path)
                        for graphic in silkscreen.graphics
                        if graphic.source_path is not None
                    },
                ),
            ),
            (
                "net-track-widths",
                partial(
                    measure_net_track_widths,
                    {
                        "F.Cu": gerber_paths[GERBER_LAYERS.index("F.Cu")],
                        "B.Cu": gerber_paths[GERBER_LAYERS.index("B.Cu")],
                    },
                    measurement,
                    width_requirements,
                    lane.board.width_measurement_tolerance_mm,
                ),
            ),
            (
                "net-path-resistance",
                partial(
                    measure_net_path_resistance,
                    measurement,
                    width_requirements,
                    routes.vias,
                    (lane.board.outer_copper_thickness_um or 0.0) / 1000.0,
                ),
            ),
        ),
        pipeline_workers,
    )
    silk_evidence = cast(dict[str, object], measurement_stages[0])
    width_evidence = cast(dict[str, object], measurement_stages[1])
    path_evidence = cast(dict[str, object], measurement_stages[2])
    net_evidence = cast(dict[str, object], width_evidence["nets"])
    for _net_name, raw in net_evidence.items():
        item = cast(dict[str, object], raw)
        item.update(cast(dict[str, object], path_evidence[_net_name]))
        item["copper_thickness_um"] = lane.board.outer_copper_thickness_um
        item["copper_thickness_source"] = lane.board.copper_thickness_source
        item["allowable_temperature_rise_k"] = lane.board.allowable_temperature_rise_k
        item["tolerance_mm"] = width_evidence["tolerance_mm"]
        item["formula_source"] = lane.board.width_basis_source
        item["ipc2221_external"] = {
            "k": lane.board.ipc2221_external_k,
            "b": lane.board.ipc2221_external_b,
            "c": lane.board.ipc2221_external_c,
        }
        if item["current_max_a"] is not None:
            thickness_mm = (lane.board.outer_copper_thickness_um or 0.0) / 1000.0
            width_mm = float(cast(float, item["measured_minimum_mm"]))
            length_mm = float(cast(float, item["total_conductor_length_mm"]))
            resistance = (
                1.724e-5 * length_mm / (width_mm * thickness_mm)
                if width_mm > 0 and thickness_mm > 0
                else None
            )
            item["series_resistance_upper_bound_ohm"] = resistance
            item["ir_drop_upper_bound_v"] = (
                resistance * float(cast(float, item["current_max_a"]))
                if resistance is not None
                else None
            )
            derived_width = float(cast(float, item["derived_width_mm"]))
            item["adopted_to_derived_width_ratio"] = (
                width_mm / derived_width if derived_width > 0 else None
            )
    width_evidence["netclasses"] = [
        {
            "name": netclass.name,
            "track_width_mm": netclass.width_mm,
            "members": list(netclass.nets),
        }
        for netclass in project.board_projection.model.netclasses
    ]
    width_evidence["dsn_class_projection"] = measure_dsn_class_correspondence(
        dsn_path,
        project.board_projection.model.netclasses,
        net_evidence,
        lane.board.width_measurement_tolerance_mm,
    )
    width_evidence["kicad_projection"] = {
        "schema": "net_settings.classes plus netclass_patterns",
        "kicad_version": kicad.version(),
        "validation": {
            "normal_drc_error_count": drc.error_count,
            "normal_drc_unconnected_count": len(drc.unconnected_items),
            "netclass_patterns_positive_control": kicad_positive_control,
        },
    }
    measurement_gate_results = run_ordered_stages(
        (
            (
                "smd-pad-centers",
                partial(
                    verify_smd_pad_centers_in_gerber,
                    gerber_paths[GERBER_LAYERS.index("F.Cu")],
                    measurement,
                ),
            ),
            (
                "ground-plane-gerbers",
                partial(
                    verify_ground_plane_gerbers,
                    gerber_paths[GERBER_LAYERS.index("F.Cu")],
                    gerber_paths[GERBER_LAYERS.index("B.Cu")],
                    project.board_projection.model,
                    stitch_vias,
                    routes,
                ),
            ),
        ),
        pipeline_workers,
    )
    plane_measurement = cast(dict[str, object], measurement_gate_results[1])
    plane_measurement["stitch_via_candidates"] = summarize_stitch_candidate_report(
        initial_stitch_report
    )
    return BoardMeasurements(
        measurement=measurement,
        drill_count=drill_count,
        silk_evidence=silk_evidence,
        width_evidence=width_evidence,
        plane_measurement=plane_measurement,
    )
