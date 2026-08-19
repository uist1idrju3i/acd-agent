"""Tests for electrical-lane visual projection wiring."""

# pyright: reportMissingTypeStubs=false

from __future__ import annotations

import stat
from pathlib import Path

import pytest
from pydantic import ValidationError

from acd.adapters.kicad.cli import KicadCli
from acd.adapters.kicad.gates import GateError
from acd.adapters.kicad.visual_projection import KicadVisualRenderer
from acd.core.board_model import BoardModel, CopperZone
from acd.core.electrical import BoardView, ElectricalLane
from acd.core.process import ExternalToolError
from acd.pipeline.visual_projection import generate_electrical_visual_projections
from acd.schema.visual_projection import (
    ElectricalVisualProjectionGates,
    ElectricalVisualProjectionPredicate,
    VisualProjectionSet,
)

_FAKE_KICAD = """\
#!/usr/bin/env python3
import os
import pathlib
import sys

if sys.argv[1:] == ["version"]:
    print("10.0.5")
    raise SystemExit(0)
if os.getenv("FAKE_FAILURE"):
    raise SystemExit(7)
output = pathlib.Path(sys.argv[sys.argv.index("-o") + 1])
if os.getenv("FAKE_MISSING_OUTPUT"):
    raise SystemExit(0)
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(
    '<svg width="29.9974mm" height="24.9936mm" '
    'viewBox="0.0000 0.0000 29.9974 24.9936">'
    f'<title>SVG Image created as {output.name} date 2026-08-19T03:45:00 </title>'
    '<path d="same"/></svg>'
)
"""


def _renderer(tmp_path: Path) -> KicadVisualRenderer:
    executable = tmp_path / "fake-kicad-cli"
    executable.write_text(_FAKE_KICAD)
    executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
    return KicadVisualRenderer(KicadCli(str(executable)))


def _lane_and_board(layer_count: int = 2) -> tuple[ElectricalLane, BoardModel]:
    lane_board = BoardView(
        node_id="electrical-board",
        width_mm=30.0,
        height_mm=25.0,
        layers=layer_count,
        thickness_mm=1.6,
        unit="mm",
        origin="upper-left",
        y_axis="down",
        min_track_mm=0.2,
        min_clearance_mm=0.2,
        via_drill_mm=0.3,
        via_diameter_mm=0.6,
        edge_copper_clearance_mm=0.3,
        antenna_keepout=False,
        ground_plane_layers=("F.Cu", "B.Cu"),
    )
    lane = ElectricalLane(components=(), nets=(), pins=(), board=lane_board)
    board = BoardModel(
        width_mm=30.0,
        height_mm=25.0,
        layers=layer_count,
        min_track_mm=0.2,
        min_clearance_mm=0.2,
        via_drill_mm=0.3,
        via_diameter_mm=0.6,
        edge_clearance_mm=0.3,
        placements=(),
        nets=(),
        copper_zones=(CopperZone("GND", ("F.Cu", "B.Cu"), 0.3, 1.0),),
    )
    return lane, board


def _passing_gates(
    predicate_names: tuple[str, ...] = ("usb_cc",),
) -> ElectricalVisualProjectionGates:
    return ElectricalVisualProjectionGates(
        erc_errors=0,
        erc_unconnected=0,
        routing_converged=True,
        drc_errors=0,
        drc_unconnected=0,
        independent_reload=True,
        silkscreen_status="measured_pass",
        dfm_status="pass",
        design_predicates=tuple(
            ElectricalVisualProjectionPredicate(name=name, status="pass", detail="ok")
            for name in predicate_names
        ),
    )


def _generate(
    out_dir: Path,
    renderer: KicadVisualRenderer,
    gates: ElectricalVisualProjectionGates | None = None,
    layer_count: int = 2,
) -> VisualProjectionSet:
    lane, board = _lane_and_board(layer_count)
    source_schematic = out_dir / "gd1.kicad_sch"
    source_board = out_dir / "routed" / "gd1.kicad_pcb"
    source_schematic.parent.mkdir(parents=True, exist_ok=True)
    source_board.parent.mkdir(parents=True, exist_ok=True)
    source_schematic.write_text("schematic")
    source_board.write_text("board")
    return generate_electrical_visual_projections(
        project_name="gd1",
        out_dir=out_dir,
        source_revision="r8",
        schematic=source_schematic,
        routed_board=source_board,
        lane=lane,
        board=board,
        gates=gates or _passing_gates(),
        renderer=renderer,
    )


def test_generates_electrical_projection_set_without_changing_evidence(
    tmp_path: Path,
) -> None:
    renderer = _renderer(tmp_path)
    evidence = tmp_path / "evidence-electrical.json"
    evidence.write_text('{"status":"valid","claims":[]}\n')
    before = evidence.read_bytes()

    projection_set = _generate(tmp_path / "out", renderer)

    assert projection_set.pass_evidence is False
    assert [item.projection_id for item in projection_set.projections] == [
        "gd1-b-cu",
        "gd1-f-cu",
        "gd1-schematic",
    ]
    assert [item.projection_type for item in projection_set.projections] == [
        "layered_layout_view",
        "layered_layout_view",
        "schematic_view",
    ]
    assert projection_set.identity_hash.startswith("sha256:")
    assert (tmp_path / "out/visual-projections-electrical.json").is_file()
    assert all(
        (tmp_path / "out" / item.image_path).is_file()
        for item in projection_set.projections
    )
    assert not (tmp_path / "out/hashes.json").exists()
    assert evidence.read_bytes() == before


@pytest.mark.parametrize(
    ("mutation",),
    [
        ("fail",),
        ("unknown",),
        ("missing",),
    ],
)
def test_gate_failures_stop_before_renderer(
    tmp_path: Path,
    mutation: str,
) -> None:
    gates = _passing_gates().model_copy(
        update={"dfm_status": "fail" if mutation == "fail" else "unknown"}
    )
    if mutation == "missing":
        with pytest.raises(ValidationError):
            ElectricalVisualProjectionGates.model_validate(
                gates.model_dump(mode="json", exclude={"dfm_status"})
            )
        return

    with pytest.raises(GateError, match="visual projection gate dfm_status"):
        _generate(tmp_path / "out", _renderer(tmp_path), gates)
    assert not (tmp_path / "out/visual-projections-electrical.json").exists()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("erc_errors", -1),
        ("silkscreen_status", "unexpected"),
        ("dfm_status", "unknown"),
        ("dfm_status", "unexpected"),
        ("design_predicates", ()),
    ],
)
def test_gate_contract_rejects_invalid_values(
    field: str,
    value: object,
) -> None:
    payload = _passing_gates().model_dump(mode="json")
    payload[field] = value
    with pytest.raises(ValidationError):
        ElectricalVisualProjectionGates.model_validate(payload)


def test_predicate_count_is_not_fixed(tmp_path: Path) -> None:
    predicate_names = tuple(f"predicate-{index}" for index in range(7))
    projection_set = _generate(
        tmp_path / "out",
        _renderer(tmp_path),
        _passing_gates(predicate_names),
    )
    assert projection_set.projections


@pytest.mark.parametrize(
    ("layer_count", "expected_layers"),
    [
        (2, ("gd1-b-cu", "gd1-f-cu")),
        (4, ("gd1-b-cu", "gd1-f-cu", "gd1-in1-cu", "gd1-in2-cu")),
    ],
)
def test_kicad_layer_count_mapping(
    tmp_path: Path,
    layer_count: int,
    expected_layers: tuple[str, ...],
) -> None:
    projection_set = _generate(
        tmp_path / "out",
        _renderer(tmp_path),
        layer_count=layer_count,
    )
    assert [item.projection_id for item in projection_set.projections[:-1]] == list(
        expected_layers
    )


@pytest.mark.parametrize("environment_variable", ["FAKE_FAILURE", "FAKE_MISSING_OUTPUT"])
def test_renderer_failure_stops_generation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    environment_variable: str,
) -> None:
    monkeypatch.setenv(environment_variable, "1")
    with pytest.raises(ExternalToolError):
        _generate(tmp_path / "out", _renderer(tmp_path))
    assert not (tmp_path / "out/visual-projections-electrical.json").exists()


def test_identity_hash_is_stable_when_only_time_changes(
    tmp_path: Path,
) -> None:
    out_dir = tmp_path / "out"
    first = _generate(out_dir, _renderer(tmp_path))
    second = _generate(out_dir, _renderer(tmp_path))

    assert first.identity_hash == second.identity_hash
    assert first.computed_identity_hash() == second.computed_identity_hash()


@pytest.mark.parametrize("layer_count", [0, 1, 3, 6])
def test_unsupported_kicad_layer_count_fails_closed(
    tmp_path: Path,
    layer_count: int,
) -> None:
    with pytest.raises(ValueError, match="unsupported KiCad copper layer count"):
        _generate(tmp_path / "out", _renderer(tmp_path), layer_count=layer_count)
