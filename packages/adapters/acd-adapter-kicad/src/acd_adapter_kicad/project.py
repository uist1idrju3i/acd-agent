"""Deterministic KiCad project writer.

Materializes a self-contained project directory (schematic, board, project
file, library tables) so kicad-cli runs against exactly the pinned libraries
recorded in the design graph, not whatever is configured globally.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from acd_adapter_kicad.board import BoardProjection, generate_board
from acd_adapter_kicad.library import FootprintLibrary, SymbolLibrary
from acd_adapter_kicad.schematic import PWR_FLAG_LIB_ID, generate_schematic
from acd_core.bom import bom_csv
from acd_core.electrical import BoardView, ElectricalLane


@dataclass(frozen=True)
class ProjectFiles:
    root: Path
    name: str
    schematic: Path
    board: Path
    project: Path
    bom: Path
    schematic_content: str
    board_projection: BoardProjection


def _lib_table(kind: str, entries: dict[str, Path]) -> str:
    lines = [f"({kind}_lib_table", "  (version 7)"]
    for name in sorted(entries):
        uri = entries[name]
        lines.append(
            f'  (lib (name "{name}")(type "KiCad")(uri "{uri}")(options "")(descr ""))'
        )
    lines.append(")")
    return "\n".join(lines) + "\n"


def _resolve(path_text: str, fixture_dir: Path) -> Path:
    path = Path(path_text)
    if not path.is_absolute():
        path = fixture_dir / path
    return path.resolve()


def _project_settings(filename: str, board: BoardView) -> dict[str, object]:
    """Project file carrying the graph's board constraints so DRC judges
    against the design graph, not KiCad defaults."""
    return {
        "meta": {"filename": filename, "version": 3},
        "board": {
            "design_settings": {
                "rules": {
                    "min_clearance": board.min_clearance_mm,
                    "min_copper_edge_clearance": board.edge_copper_clearance_mm,
                    "min_track_width": board.min_track_mm,
                    "min_via_diameter": board.via_diameter_mm,
                    "min_through_hole_diameter": board.via_drill_mm,
                    "min_hole_clearance": board.min_clearance_mm,
                    "min_hole_to_hole": board.min_clearance_mm,
                },
            },
        },
        "net_settings": {
            "classes": [
                {
                    "name": "Default",
                    "clearance": board.min_clearance_mm,
                    "track_width": board.min_track_mm,
                    "via_diameter": board.via_diameter_mm,
                    "via_drill": board.via_drill_mm,
                }
            ],
            "meta": {"version": 4},
        },
    }


def write_project(
    lane: ElectricalLane,
    fixture_dir: Path,
    out_dir: Path,
    name: str = "gd1",
) -> ProjectFiles:
    out_dir.mkdir(parents=True, exist_ok=True)

    symbol_libs: dict[str, Path] = {}
    footprint_libs: dict[str, Path] = {}
    for comp in lane.components:
        lib = comp.library
        sym_lib = lib.symbol.split(":", 1)[0]
        symprint = _resolve(lib.symbol_file, fixture_dir)
        symbol_libs.setdefault(sym_lib, symprint)
        fp_lib = lib.footprint.split(":", 1)[0]
        fp_dir = _resolve(lib.footprint_file, fixture_dir).parent
        footprint_libs.setdefault(fp_lib, fp_dir)
    power_lib = Path("/usr/share/kicad/symbols/power.kicad_sym")
    symbol_libs.setdefault("power", power_lib)

    symbol_library = SymbolLibrary()
    power_sha = "sha256:" + hashlib.sha256(power_lib.read_bytes()).hexdigest()
    pwr_flag_symbol = symbol_library.load(PWR_FLAG_LIB_ID, power_lib, power_sha)
    schematic_content = generate_schematic(lane, symbol_library, fixture_dir, pwr_flag_symbol)
    board_projection = generate_board(lane, FootprintLibrary(), fixture_dir)

    schematic = out_dir / f"{name}.kicad_sch"
    board = out_dir / f"{name}.kicad_pcb"
    project = out_dir / f"{name}.kicad_pro"
    bom = out_dir / f"{name}.bom.csv"

    schematic.write_text(schematic_content)
    board.write_text(board_projection.content)
    settings = _project_settings(project.name, lane.board)
    project.write_text(json.dumps(settings, sort_keys=True) + "\n")
    (out_dir / "sym-lib-table").write_text(_lib_table("sym", symbol_libs))
    (out_dir / "fp-lib-table").write_text(_lib_table("fp", footprint_libs))
    bom.write_text(bom_csv(lane))

    return ProjectFiles(
        root=out_dir,
        name=name,
        schematic=schematic,
        board=board,
        project=project,
        bom=bom,
        schematic_content=schematic_content,
        board_projection=board_projection,
    )
