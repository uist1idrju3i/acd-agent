from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from acd.core.electrical import ElectricalLane, extract_electrical_lane
from acd.core.route_candidates import (
    RouteCandidateError,
    load_route_candidates,
    parse_route_candidates,
)
from acd.schema import DesignGraph

ROOT = Path(__file__).parents[2]
FIXTURE = ROOT / "fixtures/golden-design-1/graph.json"


def _lane() -> ElectricalLane:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return extract_electrical_lane(DesignGraph.model_validate(data))


def _report(**overrides: Any) -> dict[str, Any]:
    report: dict[str, Any] = {
        "artifact_kind": "vision_route_candidates",
        "pass_evidence": False,
        "lane": "electrical",
        "proposed_nets": ["BOOT"],
        "candidates": {
            "vision": [
                {
                    "net": "BOOT",
                    "layer": "F.Cu",
                    "width_mm": 0.25,
                    "points": [[2.0, 8.0], [4.0, 10.0], [12.0, 10.0]],
                    "surrogate_metrics": {"total_length_mm": 10.83},
                }
            ],
            "vias": [],
        },
        "ranking": ["BOOT"],
        "provenance": {
            "skill_name": "acd-placement-search",
            "script_name": "vision_route_proposal.py",
            "script_sha256": f"sha256:{'1' * 64}",
            "proposal_sha256": f"sha256:{'2' * 64}",
            "placements_sha256": "deterministic-search",
            "relaxation_profile_id": "placement-relaxation-default",
            "relaxation_profile_sha256": f"sha256:{'3' * 64}",
            "graph_revision": "r1",
            "observation": {
                "tool_name": "inspect_image_with_vision",
                "profile_name": "vision-review",
                "model": "vendor/vision-model",
                "projection_id": "visual-routing-view",
                "image_hash": f"sha256:{'0' * 64}",
                "response_sha256": f"sha256:{'4' * 64}",
            },
        },
    }
    report.update(overrides)
    return report


def _wires(**overrides: Any) -> dict[str, Any]:
    wire: dict[str, Any] = {
        "net": "BOOT",
        "layer": "F.Cu",
        "width_mm": 0.25,
        "points": [[2.0, 8.0], [12.0, 10.0]],
    }
    wire.update(overrides)
    return {"vision": [wire], "vias": []}


def test_candidates_become_tool_neutral_routes() -> None:
    design, provenance = parse_route_candidates(_report(), _lane(), "r1")
    assert [wire.net for wire in design.wires] == ["BOOT"]
    assert design.wires[0].layer == "F.Cu"
    assert design.wires[0].points[0] == (2.0, 8.0)
    assert design.vias == ()
    assert provenance.skill_name == "acd-placement-search"
    assert provenance.record()["pass_evidence"] is False


def test_provenance_record_never_carries_the_vision_response() -> None:
    _, provenance = parse_route_candidates(_report(), _lane(), "r1")
    record = provenance.record()
    assert record["observation_response_sha256"] == provenance.observation_response_sha256
    assert "response" not in record


def test_load_reads_a_report_written_outside_acd(tmp_path: Path) -> None:
    path = tmp_path / "candidates.json"
    path.write_text(json.dumps(_report()), encoding="utf-8")
    design, provenance = load_route_candidates(path, _lane(), "r1")
    assert design.wires[0].width_mm == 0.25
    assert provenance.graph_revision == "r1"


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"artifact_kind": "vision_route_proposal"}, "artifact_kind"),
        ({"pass_evidence": True}, "pass_evidence"),
        ({"lane": "mechanical"}, "electrical lane"),
        ({"candidates": {"vision": [], "vias": []}}, "no wires"),
        ({"candidates": {"vision": [_wires()["vision"][0]]}}, "vias"),
        (
            {"candidates": {"vision": [_wires()["vision"][0]], "vias": [{"net": "BOOT"}]}},
            "x_mm",
        ),
        ({"candidates": {"vision": [_wires()["vision"][0]], "vias": "none"}}, "must be an array"),
        ({"candidates": _wires(net="NOT_A_NET")}, "unknown net"),
        ({"candidates": _wires(layer="In1.Cu")}, "unsupported layer"),
        ({"candidates": _wires(width_mm=0.01)}, "below the declared minimum"),
        ({"candidates": _wires(width_mm="wide")}, "width_mm"),
        ({"candidates": _wires(points=[[2.0, 8.0]])}, "at least two points"),
        ({"candidates": _wires(points=[[2.0, 8.0], [2.0, 8.0]])}, "repeated point"),
        ({"candidates": _wires(points=[[2.0, 8.0], [12.0]])}, r"\[x, y\]"),
        ({"candidates": _wires(points=[[2.0, 8.0], [12.0, float("inf")]])}, "finite"),
    ],
)
def test_broken_candidate_reports_fail_closed(overrides: dict[str, Any], match: str) -> None:
    with pytest.raises(RouteCandidateError, match=match):
        parse_route_candidates(_report(**overrides), _lane(), "r1")


def test_duplicate_wires_fail_closed() -> None:
    wire = _wires()["vision"][0]
    report = _report(candidates={"vision": [wire, dict(wire)], "vias": []})
    with pytest.raises(RouteCandidateError, match="duplicate wire"):
        parse_route_candidates(report, _lane(), "r1")


def _via_candidates(**overrides: Any) -> dict[str, Any]:
    """One connection that changes layer at a via, as the skill reports it."""
    via: dict[str, Any] = {
        "net": "BOOT",
        "x_mm": 8.0,
        "y_mm": 10.0,
        "drill_mm": 0.3,
        "diameter_mm": 0.6,
    }
    via.update(overrides)
    return {
        "vision": [
            {
                "net": "BOOT",
                "layer": "F.Cu",
                "from_pad": "U1-23",
                "to_pad": "SW2-1",
                "width_mm": 0.25,
                "points": [[2.0, 8.0], [8.0, 10.0]],
            },
            {
                "net": "BOOT",
                "layer": "B.Cu",
                "from_pad": "U1-23",
                "to_pad": "SW2-1",
                "width_mm": 0.25,
                "points": [[8.0, 10.0], [12.0, 12.0]],
            },
        ],
        "vias": [via],
    }


def test_a_via_between_two_layers_becomes_a_tool_neutral_via() -> None:
    design, _ = parse_route_candidates(
        _report(candidates=_via_candidates()), _lane(), "r1"
    )
    assert [wire.layer for wire in design.wires] == ["B.Cu", "F.Cu"]
    assert [(via.net, via.x_mm, via.y_mm) for via in design.vias] == [("BOOT", 8.0, 10.0)]


def test_several_connections_of_one_net_stay_separate_wires() -> None:
    candidates = {
        "vision": [
            {
                "net": "LED",
                "layer": "F.Cu",
                "from_pad": "U1-21",
                "to_pad": "R6-1",
                "width_mm": 0.25,
                "points": [[2.0, 8.0], [6.0, 10.0]],
            },
            {
                "net": "LED",
                "layer": "F.Cu",
                "from_pad": "R6-1",
                "to_pad": "TP5-1",
                "width_mm": 0.25,
                "points": [[6.0, 10.0], [14.0, 12.0]],
            },
        ],
        "vias": [],
    }
    design, _ = parse_route_candidates(
        _report(proposed_nets=["LED"], candidates=candidates), _lane(), "r1"
    )
    assert len(design.wires) == 2


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"net": "NOT_A_NET"}, "unknown net"),
        ({"drill_mm": 0.1}, "below the declared minimum"),
        ({"diameter_mm": 0.45}, "below the declared minimum"),
        ({"diameter_mm": 0.3, "drill_mm": 0.3}, "not usable"),
        ({"x_mm": 9.0}, "not reached by wires on two layers"),
    ],
)
def test_broken_vias_fail_closed(overrides: dict[str, Any], match: str) -> None:
    report = _report(candidates=_via_candidates(**overrides))
    with pytest.raises(RouteCandidateError, match=match):
        parse_route_candidates(report, _lane(), "r1")


def test_duplicate_vias_fail_closed() -> None:
    candidates = _via_candidates()
    candidates["vias"] = [candidates["vias"][0], dict(candidates["vias"][0])]
    with pytest.raises(RouteCandidateError, match="duplicate via"):
        parse_route_candidates(_report(candidates=candidates), _lane(), "r1")


def test_a_via_of_a_single_layer_candidate_fails_closed() -> None:
    candidates = _via_candidates()
    candidates["vision"] = [candidates["vision"][0]]
    with pytest.raises(RouteCandidateError, match="two layers"):
        parse_route_candidates(_report(candidates=candidates), _lane(), "r1")


@pytest.mark.parametrize(
    "removed",
    [
        "skill_name",
        "script_sha256",
        "proposal_sha256",
        "relaxation_profile_id",
        "relaxation_profile_sha256",
        "graph_revision",
    ],
)
def test_missing_provenance_fails_closed(removed: str) -> None:
    report = _report()
    del report["provenance"][removed]
    with pytest.raises(RouteCandidateError, match="provenance is missing"):
        parse_route_candidates(report, _lane(), "r1")


def test_missing_observation_provenance_fails_closed() -> None:
    report = _report()
    del report["provenance"]["observation"]["image_hash"]
    with pytest.raises(RouteCandidateError, match="observation provenance is missing"):
        parse_route_candidates(report, _lane(), "r1")


def test_candidate_from_another_revision_fails_closed() -> None:
    with pytest.raises(RouteCandidateError, match="not 'r2'"):
        parse_route_candidates(_report(), _lane(), "r2")


def test_unreadable_report_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "candidates.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(RouteCandidateError, match="unreadable"):
        load_route_candidates(path, _lane(), "r1")


def test_non_object_report_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "candidates.json"
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(RouteCandidateError, match="JSON object"):
        load_route_candidates(path, _lane(), "r1")
