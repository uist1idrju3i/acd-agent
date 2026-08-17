"""Fabrication measurements, checks, assembly exports, and packaging helpers."""
# pyright: reportUnusedImport=false, reportPrivateUsage=false, reportPrivateImportUsage=false, reportUnknownParameterType=false, reportMissingParameterType=false, reportUnknownArgumentType=false

# ruff: noqa: I001,RUF100,F401,E501

from collections.abc import Mapping
from pathlib import Path

from .common import *  # noqa: F401,F403
from .geometry import rotate  # noqa: F401
from .archive import deterministic_zip, zip_content_hash  # noqa: F401
from .assembly import (  # noqa: F401
    apply_cpl_contract,
    cross_validate_bom,
    cross_validate_cpl,
    jlcpcb_bom_csv,
    jlcpcb_cpl_csv,
    parse_pos_csv,
)
from .common import (  # noqa: F401
    BoardMeasurement,
    CplBasisError,
    FabOutputError,
    FootprintMeasurement,
    GerberRegionRecord,
    PadMeasurement,
    SegmentMeasurement,
    UncoveredStitchViasError,
    ViaMeasurement,
)
from acd.core.fab import FabProfile
from acd.core.silkscreen import SilkscreenLane
from .cpl_orientation import (  # noqa: F401
    derive_lcsc_rotation_offset,
    load_lcsc_pin_centers,
    load_lcsc_pin_geometries,
    verify_cpl_pin_function_declaration,
    verify_lcsc_rotation_evidence,
)
from .dfm import run_dfm  # noqa: F401
from .gerber import (  # noqa: F401
    verify_ground_plane_gerbers,
    verify_smd_pad_centers_in_gerber,
)
from .routed_board import (  # noqa: F401
    GerberFile,
    measure_net_path_resistance,
    measure_net_track_widths,
    parse_routed_board,
    read_drill_measurement,
)

from . import silkscreen as _silkscreen
from .silkscreen import (
    _gerber_silk_objects,
    build_silkscreen_context as _build_silkscreen_context,
    measure_silkscreen as _measure_silkscreen,
)


def measure_silkscreen(*args, **kwargs):
    _silkscreen._gerber_silk_objects = _gerber_silk_objects
    return _measure_silkscreen(*args, **kwargs)


def build_silkscreen_context(
    silk_paths: Mapping[str, Path],
    mask_paths: Mapping[str, Path],
    edge_path: Path,
    measurement: BoardMeasurement,
    declarations: SilkscreenLane,
    profile: FabProfile,
) -> dict[str, object]:
    _silkscreen._gerber_silk_objects = _gerber_silk_objects
    return _build_silkscreen_context(
        silk_paths, mask_paths, edge_path, measurement, declarations, profile
    )


__all__ = [
    "BoardMeasurement",
    "CplBasisError",
    "FabOutputError",
    "FootprintMeasurement",
    "GerberRegionRecord",
    "PadMeasurement",
    "SegmentMeasurement",
    "UncoveredStitchViasError",
    "ViaMeasurement",
    "apply_cpl_contract",
    "build_silkscreen_context",
    "cross_validate_bom",
    "cross_validate_cpl",
    "derive_lcsc_rotation_offset",
    "deterministic_zip",
    "jlcpcb_bom_csv",
    "jlcpcb_cpl_csv",
    "load_lcsc_pin_centers",
    "load_lcsc_pin_geometries",
    "measure_net_path_resistance",
    "measure_net_track_widths",
    "measure_silkscreen",
    "parse_pos_csv",
    "parse_routed_board",
    "read_drill_measurement",
    "rotate",
    "run_dfm",
    "verify_cpl_pin_function_declaration",
    "verify_ground_plane_gerbers",
    "verify_lcsc_rotation_evidence",
    "verify_smd_pad_centers_in_gerber",
    "zip_content_hash",
]
