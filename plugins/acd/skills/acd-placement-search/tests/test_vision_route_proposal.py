"""Vision routing candidate tests (skill asset, separate from the ACD core)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from acd.adapters.kicad.placement import Rect
from vision_proposal import (
    RelaxationProfile,
    VisionProposalError,
    deterministic_placements,
    electrical_context,
    load_relaxation_profile,
)
from vision_route_proposal import (
    ProposedRoute,
    RouteContext,
    blockages,
    legalize_proposal,
    legalize_route,
    octilinearize,
    parse_route_proposal,
    route_context,
    route_metrics,
)

SKILL_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[5]
SCRIPT = SKILL_ROOT / "scripts" / "vision_route_proposal.py"
DEFAULT_PROFILE = REPO_ROOT / "profiles" / "search" / "placement-relaxation-profile-default.json"
FIXTURE_DIR = REPO_ROOT / "fixtures" / "golden-design-1"
GRAPH = FIXTURE_DIR / "graph.json"
FAB_PROFILE = REPO_ROOT / "profiles" / "jlcpcb" / "fab-profile-jlcpcb-fr4-2l-1oz.json"


def _payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "artifact_kind": "vision_route_proposal",
        "pass_evidence": False,
        "observation": {
            "tool_name": "inspect_image_with_vision",
            "profile_name": "vision-review",
            "model": "vendor/vision-model",
            "projection_id": "visual-routing-view",
            "image_hash": f"sha256:{'0' * 64}",
            "response": "Route BOOT below the regulator, then across to the MCU.",
        },
        "proposals": [
            {
                "net": "BOOT",
                "layer": "F.Cu",
                "waypoints": [{"x_mm": 6.3, "y_mm": 9.2}, {"x_mm": 15.2, "y_mm": 8.8}],
            },
            {
                "net": "CC2",
                "layer": "F.Cu",
                "waypoints": [{"x_mm": 22.1, "y_mm": 17.6}],
            },
        ],
    }
    payload.update(overrides)
    return payload


def _profile(**overrides: Any) -> RelaxationProfile:
    values: dict[str, Any] = {
        "profile_id": "test",
        "grid_step_mm": 0.25,
        "max_shift_mm": 5.0,
        "rotation_step_deg": 90.0,
        "allowed_rotations_deg": (0.0, 90.0, 180.0, 270.0),
        "arc_tracks": False,
        "off_grid_angles": False,
    }
    values.update(overrides)
    return RelaxationProfile(**values)


def _context(**overrides: Any) -> RouteContext:
    values: dict[str, Any] = {
        "region": Rect(0.0, 0.0, 20.0, 10.0),
        "clearance_mm": 0.2,
        "endpoints": {("F.Cu", "N1"): ((1.0, 1.0), (19.0, 1.0))},
        "widths_mm": {"N1": 0.2},
        "obstacles": {("F.Cu", "N2"): (Rect(9.0, 0.5, 11.0, 1.5),)},
    }
    values.update(overrides)
    return RouteContext(**values)


def test_parse_accepts_a_numeric_routing_proposal() -> None:
    proposal = parse_route_proposal(_payload())
    assert [route.net for route in proposal.routes] == ["BOOT", "CC2"]
    assert proposal.routes[0].waypoints == ((6.3, 9.2), (15.2, 8.8))
    assert proposal.observation.response_sha256.startswith("sha256:")


BROKEN_PROPOSALS: list[tuple[dict[str, Any], str]] = [
    ({"artifact_kind": "other"}, "artifact_kind"),
    ({"pass_evidence": True}, "pass_evidence"),
    ({"proposals": []}, "non-empty array"),
    (
        {
            "proposals": [
                {"net": "BOOT", "layer": "F.Cu", "waypoints": [{"x_mm": 1.0, "y_mm": 1.0}]},
                {"net": "BOOT", "layer": "B.Cu", "waypoints": [{"x_mm": 2.0, "y_mm": 2.0}]},
            ]
        },
        "duplicate proposal",
    ),
    (
        {
            "proposals": [
                {"net": "BOOT", "layer": "In1.Cu", "waypoints": [{"x_mm": 1.0, "y_mm": 1.0}]}
            ]
        },
        "unsupported copper layer",
    ),
    (
        {
            "proposals": [
                {
                    "net": "BOOT",
                    "layer": "F.Cu",
                    "waypoints": [{"x_mm": 1.0, "y_mm": 1.0}],
                    "radius_mm": 0.5,
                }
            ]
        },
        "arc geometry",
    ),
    (
        {"proposals": [{"net": "BOOT", "layer": "F.Cu", "waypoints": []}]},
        "non-empty array",
    ),
    (
        {
            "proposals": [
                {"net": "BOOT", "layer": "F.Cu", "waypoints": [{"x_mm": 1.0, "y_mm": "x"}]}
            ]
        },
        "y_mm",
    ),
    (
        {
            "observation": {
                "tool_name": "read_text",
                "profile_name": "vision-review",
                "model": "vendor/vision-model",
                "projection_id": "visual-routing-view",
                "image_hash": f"sha256:{'0' * 64}",
                "response": "text",
            }
        },
        "tool_name",
    ),
    (
        {
            "observation": {
                "tool_name": "inspect_image_with_vision",
                "profile_name": "vision-review",
                "model": "vendor/vision-model",
                "projection_id": "visual-routing-view",
                "image_hash": "not-a-hash",
                "response": "text",
            }
        },
        "image_hash",
    ),
    (
        {
            "observation": {
                "tool_name": "inspect_image_with_vision",
                "profile_name": "vision-review",
                "model": "vendor/vision-model",
                "projection_id": "visual-routing-view",
                "image_hash": f"sha256:{'0' * 64}",
                "response": "",
            }
        },
        "response",
    ),
]


@pytest.mark.parametrize(("overrides", "match"), BROKEN_PROPOSALS)
def test_parse_fails_closed_on_broken_proposals(overrides: dict[str, Any], match: str) -> None:
    with pytest.raises(VisionProposalError, match=match):
        parse_route_proposal(_payload(**overrides))


def test_octilinearize_splits_a_free_angle_into_45_and_90_degrees() -> None:
    assert octilinearize((0.0, 0.0), (4.0, 1.0)) == ((0.0, 0.0), (1.0, 1.0), (4.0, 1.0))
    assert octilinearize((0.0, 0.0), (2.0, 2.0)) == ((0.0, 0.0), (2.0, 2.0))
    assert octilinearize((0.0, 0.0), (0.0, 3.0)) == ((0.0, 0.0), (0.0, 3.0))


def test_legalize_pins_the_endpoints_and_keeps_only_legal_angles() -> None:
    context = _context()
    route = ProposedRoute(net="N1", layer="F.Cu", waypoints=((10.13, 4.02),))
    candidate = legalize_route(route, context, _profile())
    assert candidate.points[0] == (1.0, 1.0)
    assert candidate.points[-1] == (19.0, 1.0)
    assert candidate.width_mm == 0.2
    for start, end in zip(candidate.points, candidate.points[1:], strict=False):
        delta_x, delta_y = abs(end[0] - start[0]), abs(end[1] - start[1])
        assert delta_x < 1e-9 or delta_y < 1e-9 or abs(delta_x - delta_y) < 1e-9


def test_legalize_repairs_a_hop_that_crosses_foreign_copper() -> None:
    context = _context()
    route = ProposedRoute(net="N1", layer="F.Cu", waypoints=((10.0, 1.0),))
    candidate = legalize_route(route, context, _profile())
    metrics = route_metrics(candidate, context)
    assert candidate.repaired_hops >= 1
    assert metrics.min_clearance_mm >= context.clearance_mm + candidate.width_mm / 2.0


def test_legalize_keeps_clearance_from_an_already_legalized_wire() -> None:
    context = _context(
        endpoints={
            ("F.Cu", "N1"): ((1.0, 1.0), (19.0, 1.0)),
            ("F.Cu", "N3"): ((1.0, 3.0), (19.0, 3.0)),
        },
        widths_mm={"N1": 0.2, "N3": 0.2},
    )
    first = legalize_route(
        ProposedRoute(net="N1", layer="F.Cu", waypoints=((10.0, 1.0),)),
        context,
        _profile(),
    )
    second = legalize_route(
        ProposedRoute(net="N3", layer="F.Cu", waypoints=((10.0, 1.1),)),
        context,
        _profile(),
        (first,),
    )
    metrics = route_metrics(second, context, (first,))
    assert metrics.min_clearance_mm >= context.clearance_mm + 0.2


def test_legalize_is_deterministic() -> None:
    context = _context()
    route = ProposedRoute(net="N1", layer="F.Cu", waypoints=((10.0, 1.0),))
    first = legalize_route(route, context, _profile())
    second = legalize_route(route, context, _profile())
    assert first == second


def test_legalize_fails_closed_on_a_net_that_needs_vias() -> None:
    context = _context()
    route = ProposedRoute(net="N1", layer="B.Cu", waypoints=((10.0, 4.0),))
    with pytest.raises(VisionProposalError, match="without vias"):
        legalize_route(route, context, _profile())


def test_legalize_fails_closed_on_an_unknown_net() -> None:
    context = _context()
    route = ProposedRoute(net="MISSING", layer="F.Cu", waypoints=((10.0, 4.0),))
    with pytest.raises(VisionProposalError, match="two-pad net"):
        legalize_route(route, context, _profile())


def test_legalize_fails_closed_when_no_legal_route_exists() -> None:
    context = _context(
        obstacles={("F.Cu", "N2"): (Rect(9.0, -1.0, 11.0, 11.0),)},
    )
    route = ProposedRoute(net="N1", layer="F.Cu", waypoints=((10.0, 1.0),))
    with pytest.raises(VisionProposalError, match="no legal detour"):
        legalize_route(route, context, _profile())


def test_legalize_fails_closed_when_a_waypoint_cannot_be_shifted_enough() -> None:
    context = _context(
        obstacles={("F.Cu", "N2"): (Rect(4.0, -1.0, 16.0, 11.0),)},
        endpoints={("F.Cu", "N1"): ((1.0, 1.0), (2.0, 1.0))},
    )
    route = ProposedRoute(net="N1", layer="F.Cu", waypoints=((10.0, 5.0),))
    with pytest.raises(VisionProposalError, match="declared shift"):
        legalize_route(route, context, _profile(max_shift_mm=1.0))


def test_blockages_ignore_pads_of_other_layers() -> None:
    context = _context(
        obstacles={
            ("F.Cu", "N2"): (Rect(9.0, 0.5, 11.0, 1.5),),
            ("B.Cu", "N4"): (Rect(2.0, 0.5, 4.0, 1.5),),
        }
    )
    labels = [item.label for item in blockages("N1", "F.Cu", 0.2, context, ())]
    assert labels == ["net 'N2' pads"]


def test_electrical_route_context_uses_the_declared_board_and_widths() -> None:
    graph = json.loads(GRAPH.read_text(encoding="utf-8"))
    electrical = _electrical()
    context = route_context(electrical, deterministic_placements(electrical), 0.127)
    assert graph["revision"] == "r1"
    assert context.clearance_mm > 0.0
    assert ("F.Cu", "BOOT") in context.endpoints
    assert context.widths_mm["BOOT"] >= context.clearance_mm


def test_legalize_proposal_covers_every_proposed_net() -> None:
    electrical = _electrical()
    context = route_context(electrical, deterministic_placements(electrical), 0.127)
    proposal = parse_route_proposal(_payload())
    accepted = legalize_proposal(proposal, context, load_relaxation_profile(DEFAULT_PROFILE))
    assert [candidate.net for candidate, _ in accepted] == ["BOOT", "CC2"]
    assert all(len(candidate.points) >= 2 for candidate, _ in accepted)


def test_legalize_proposal_fails_closed_on_arc_relaxation() -> None:
    electrical = _electrical()
    context = route_context(electrical, deterministic_placements(electrical), 0.127)
    proposal = parse_route_proposal(_payload())
    with pytest.raises(VisionProposalError, match="arc tracks"):
        legalize_proposal(proposal, context, _profile(arc_tracks=True))


def _electrical() -> Any:
    graph_document = json.loads(GRAPH.read_text(encoding="utf-8"))
    from acd.schema.design_graph import DesignGraph

    return electrical_context(
        DesignGraph.model_validate(graph_document), FIXTURE_DIR, FAB_PROFILE
    )


def _run_cli(
    tmp_path: Path, payload: dict[str, Any], *extra: str
) -> subprocess.CompletedProcess[str]:
    proposal = tmp_path / "proposal.json"
    proposal.write_text(json.dumps(payload), encoding="utf-8")
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--proposal",
            str(proposal),
            "--input",
            str(GRAPH),
            "--relaxation-profile",
            str(DEFAULT_PROFILE),
            "--fixture-dir",
            str(FIXTURE_DIR),
            "--fab-profile",
            str(FAB_PROFILE),
            "--output",
            str(tmp_path / "candidates.json"),
            *extra,
        ],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env={"PYTHONPATH": str(SKILL_ROOT / "scripts"), "PATH": "/usr/bin:/bin"},
        check=False,
    )


def test_cli_reports_routing_candidates_with_provenance(tmp_path: Path) -> None:
    result = _run_cli(tmp_path, _payload())
    assert result.returncode == 0, result.stderr
    report = json.loads((tmp_path / "candidates.json").read_text(encoding="utf-8"))
    assert report["artifact_kind"] == "vision_route_candidates"
    assert report["pass_evidence"] is False
    assert report["lane"] == "electrical"
    assert report["candidates"]["vias"] == []
    assert [wire["net"] for wire in report["candidates"]["vision"]] == ["BOOT", "CC2"]
    assert sorted(report["ranking"]) == ["BOOT", "CC2"]
    provenance = report["provenance"]
    assert provenance["skill_name"] == "acd-placement-search"
    assert provenance["script_name"] == "vision_route_proposal.py"
    assert provenance["script_sha256"].startswith("sha256:")
    assert provenance["proposal_sha256"].startswith("sha256:")
    assert provenance["placements_sha256"] == "deterministic-search"
    assert provenance["relaxation_profile_id"] == "placement-relaxation-default"
    assert provenance["graph_revision"] == "r1"
    assert "response" not in provenance["observation"]


def test_cli_is_deterministic(tmp_path: Path) -> None:
    outputs: list[str] = []
    for name in ("first", "second"):
        run_dir = tmp_path / name
        run_dir.mkdir()
        result = _run_cli(run_dir, _payload())
        assert result.returncode == 0, result.stderr
        outputs.append((run_dir / "candidates.json").read_text(encoding="utf-8"))
    assert outputs[0] == outputs[1]


def test_cli_fails_closed_on_an_evidence_claiming_proposal(tmp_path: Path) -> None:
    result = _run_cli(tmp_path, _payload(pass_evidence=True))
    assert result.returncode != 0
    assert "pass_evidence" in result.stderr
    assert not (tmp_path / "candidates.json").exists()


def test_cli_fails_closed_on_a_multi_pad_net(tmp_path: Path) -> None:
    payload = _payload(
        proposals=[
            {"net": "GND", "layer": "F.Cu", "waypoints": [{"x_mm": 10.0, "y_mm": 10.0}]}
        ]
    )
    result = _run_cli(tmp_path, payload)
    assert result.returncode != 0
    assert "two-pad net" in result.stderr
    assert not (tmp_path / "candidates.json").exists()
