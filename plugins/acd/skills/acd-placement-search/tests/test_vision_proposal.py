"""Vision proposal intake tests (skill asset, separate from the ACD core)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from acd.adapters.kicad.placement import Rect
from vision_proposal import (
    LegalizationContext,
    RelaxationProfile,
    VisionProposalError,
    electrical_context,
    legalization_metrics,
    legalize_proposal,
    load_relaxation_profile,
    mechanical_context,
    parse_vision_proposal,
    snap_rotation,
)

SKILL_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[5]
SCRIPT = SKILL_ROOT / "scripts" / "vision_proposal.py"
DEFAULT_PROFILE = REPO_ROOT / "profiles" / "search" / "placement-relaxation-profile-default.json"
FIXTURE_DIR = REPO_ROOT / "fixtures" / "golden-design-1"
GRAPH = FIXTURE_DIR / "graph.json"
FAB_PROFILE = REPO_ROOT / "profiles" / "jlcpcb" / "fab-profile-jlcpcb-fr4-2l-1oz.json"


def _payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "artifact_kind": "vision_placement_proposal",
        "pass_evidence": False,
        "lane": "electrical",
        "observation": {
            "tool_name": "inspect_image_with_vision",
            "profile_name": "vision-review",
            "model": "vendor/vision-model",
            "projection_id": "visual-placement-view",
            "image_hash": f"sha256:{'0' * 64}",
            "response": "U1 near the top edge, C1 next to U1.",
        },
        "proposals": [
            {"item_id": "U1", "x_mm": 5.0, "y_mm": 5.0, "rotation_deg": 47.0},
            {"item_id": "C1", "x_mm": 8.0, "y_mm": 5.0, "rotation_deg": 0.0},
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


def _context(**overrides: Any) -> LegalizationContext:
    values: dict[str, Any] = {
        "lane": "electrical",
        "region": Rect(0.0, 0.0, 20.0, 15.0),
        "extents": {
            "U1": (-2.0, -1.0, 2.0, 1.0),
            "C1": (-1.0, -0.5, 1.0, 0.5),
        },
        "keepouts": (),
    }
    values.update(overrides)
    return LegalizationContext(**values)


def _profile_document(**overrides: Any) -> dict[str, Any]:
    document: dict[str, Any] = {
        "schema_version": "1.0",
        "profile_id": "test",
        "position": {"grid_step_mm": 0.25, "max_legalization_shift_mm": 5.0},
        "rotation": {
            "step_deg": 90,
            "allowed_deg": [0, 90, 180, 270],
            "relaxation_evidence_status": "absent",
        },
        "routing": {
            "arc_tracks": False,
            "off_grid_angles": False,
            "relaxation_evidence_status": "absent",
        },
        "relaxation_evidence": [],
    }
    document.update(overrides)
    return document


def _write_profile(tmp_path: Path, document: dict[str, Any]) -> Path:
    path = tmp_path / "relaxation.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def test_proposal_keeps_only_numeric_candidates_and_provenance() -> None:
    proposal = parse_vision_proposal(_payload())
    assert [item.item_id for item in proposal.items] == ["C1", "U1"]
    assert proposal.observation.projection_id == "visual-placement-view"
    assert proposal.observation.response_sha256.startswith("sha256:")
    assert not hasattr(proposal.observation, "response")


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"artifact_kind": "visual_vision_observation"}, "artifact_kind"),
        ({"pass_evidence": True}, "pass_evidence"),
        ({"lane": "firmware"}, "unsupported lane"),
        ({"proposals": []}, "non-empty array"),
        (
            {
                "proposals": [
                    {"item_id": "U1", "x_mm": 1.0, "y_mm": 1.0, "rotation_deg": 0.0},
                    {"item_id": "U1", "x_mm": 2.0, "y_mm": 1.0, "rotation_deg": 0.0},
                ]
            },
            "duplicate proposal",
        ),
        (
            {"proposals": [{"item_id": "U1", "x_mm": "1", "y_mm": 1.0, "rotation_deg": 0.0}]},
            "x_mm must be a number",
        ),
    ],
)
def test_proposal_fails_closed_on_contract_violations(
    overrides: dict[str, Any], match: str
) -> None:
    with pytest.raises(VisionProposalError, match=match):
        parse_vision_proposal(_payload(**overrides))


@pytest.mark.parametrize(
    ("observation_overrides", "match"),
    [
        ({"response": "   "}, "response must be a non-empty string"),
        ({"image_hash": "0" * 64}, "image_hash must be a sha256"),
        ({"model": ""}, "model must be a non-empty string"),
        ({"tool_name": "read_image"}, "tool_name"),
    ],
)
def test_proposal_fails_closed_on_missing_provenance(
    observation_overrides: dict[str, Any], match: str
) -> None:
    observation = dict(_payload()["observation"])
    observation.update(observation_overrides)
    with pytest.raises(VisionProposalError, match=match):
        parse_vision_proposal(_payload(observation=observation))


def test_rotation_snaps_to_the_permitted_set() -> None:
    profile = _profile()
    assert snap_rotation(47.0, profile) == 90.0
    assert snap_rotation(-1.0, profile) == 0.0
    assert snap_rotation(45.0, profile) == 0.0
    assert snap_rotation(359.0, profile) == 0.0


def test_legalization_is_deterministic_and_respects_the_region() -> None:
    proposal = parse_vision_proposal(_payload())
    context = _context()
    first = legalize_proposal(proposal, context, _profile())
    second = legalize_proposal(proposal, context, _profile())
    assert first == second
    assert {item.item_id: item.rotation_deg for item in first} == {"C1": 0.0, "U1": 90.0}
    for item in first:
        x1, _y1, _x2, y2 = context.extents[item.item_id]
        assert item.x_mm + x1 >= context.region.x1 - 1e-9
        assert item.y_mm + y2 <= context.region.y2 + 1e-9


def test_legalization_separates_overlapping_proposals() -> None:
    payload = _payload(
        proposals=[
            {"item_id": "U1", "x_mm": 5.0, "y_mm": 5.0, "rotation_deg": 0.0},
            {"item_id": "C1", "x_mm": 5.0, "y_mm": 5.0, "rotation_deg": 0.0},
        ]
    )
    legalized = legalize_proposal(parse_vision_proposal(payload), _context(), _profile())
    by_id = {item.item_id: item for item in legalized}
    assert by_id["C1"].x_mm != by_id["U1"].x_mm or by_id["C1"].y_mm != by_id["U1"].y_mm


def test_legalization_fails_closed_outside_the_shift_limit() -> None:
    payload = _payload(
        proposals=[{"item_id": "U1", "x_mm": 60.0, "y_mm": 5.0, "rotation_deg": 0.0}]
    )
    with pytest.raises(VisionProposalError, match="no legal position"):
        legalize_proposal(parse_vision_proposal(payload), _context(), _profile())


def test_legalization_fails_closed_on_unknown_targets() -> None:
    payload = _payload(
        proposals=[{"item_id": "R9", "x_mm": 5.0, "y_mm": 5.0, "rotation_deg": 0.0}]
    )
    with pytest.raises(VisionProposalError, match="unknown proposal targets"):
        legalize_proposal(parse_vision_proposal(payload), _context(), _profile())


def test_legalization_fails_closed_on_lane_mismatch() -> None:
    proposal = parse_vision_proposal(_payload())
    with pytest.raises(VisionProposalError, match="lane"):
        legalize_proposal(proposal, _context(lane="mechanical"), _profile())


def test_legalization_fails_closed_when_a_keepout_blocks_the_area() -> None:
    payload = _payload(
        proposals=[{"item_id": "U1", "x_mm": 5.0, "y_mm": 5.0, "rotation_deg": 0.0}]
    )
    context = _context(keepouts=(Rect(0.0, 0.0, 20.0, 15.0),))
    with pytest.raises(VisionProposalError, match="no legal position"):
        legalize_proposal(parse_vision_proposal(payload), context, _profile())


def test_metrics_report_the_legalization_displacement() -> None:
    proposal = parse_vision_proposal(_payload())
    context = _context()
    legalized = legalize_proposal(proposal, context, _profile())
    metrics = legalization_metrics(proposal.items, legalized, context)
    assert metrics.rotation_changes == 1
    assert metrics.max_shift_mm >= 0.0
    assert metrics.total_shift_mm >= metrics.max_shift_mm - 1e-9
    assert metrics.min_item_gap_mm >= 0.0
    assert metrics.min_region_gap_mm >= 0.0


def test_default_profile_keeps_the_90_degree_step() -> None:
    profile = load_relaxation_profile(DEFAULT_PROFILE)
    assert profile.rotation_step_deg == 90.0
    assert profile.allowed_rotations_deg == (0.0, 90.0, 180.0, 270.0)
    assert not profile.arc_tracks
    assert not profile.off_grid_angles


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        (
            {
                "rotation": {
                    "step_deg": 1,
                    "allowed_deg": [0, 1, 2],
                    "relaxation_evidence_status": "absent",
                }
            },
            "rotation relaxation",
        ),
        (
            {
                "rotation": {
                    "step_deg": 45,
                    "allowed_deg": [0, 45, 90],
                    "relaxation_evidence_status": "estimated",
                }
            },
            "rotation relaxation",
        ),
        (
            {
                "routing": {
                    "arc_tracks": True,
                    "off_grid_angles": False,
                    "relaxation_evidence_status": "absent",
                }
            },
            "routing relaxation",
        ),
        ({"schema_version": "2.0"}, "schema_version"),
        (
            {"position": {"grid_step_mm": 0.0, "max_legalization_shift_mm": 5.0}},
            "must be positive",
        ),
        (
            {
                "rotation": {
                    "step_deg": 90,
                    "allowed_deg": [90, 0],
                    "relaxation_evidence_status": "absent",
                }
            },
            "unique and sorted",
        ),
    ],
)
def test_profile_fails_closed_on_unmeasured_relaxation(
    tmp_path: Path, overrides: dict[str, Any], match: str
) -> None:
    path = _write_profile(tmp_path, _profile_document(**overrides))
    with pytest.raises(VisionProposalError, match=match):
        load_relaxation_profile(path)


def test_profile_accepts_relaxation_with_measured_evidence(tmp_path: Path) -> None:
    path = _write_profile(
        tmp_path,
        _profile_document(
            rotation={
                "step_deg": 45,
                "allowed_deg": [0, 45, 90, 135, 180, 225, 270, 315],
                "relaxation_evidence_status": "measured",
            },
            relaxation_evidence=[
                {"claim": "45 degree rotation measured on the assembly line", "path": "out/x.json"}
            ],
        ),
    )
    profile = load_relaxation_profile(path)
    assert profile.rotation_step_deg == 45.0
    assert snap_rotation(47.0, profile) == 45.0


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


def _electrical_payload() -> dict[str, Any]:
    return _payload(
        proposals=[
            {"item_id": "U2", "x_mm": 4.4, "y_mm": 15.3, "rotation_deg": 87.0},
            {"item_id": "C1", "x_mm": 7.1, "y_mm": 19.9, "rotation_deg": 2.0},
        ]
    )


def _mechanical_payload() -> dict[str, Any]:
    observation = dict(_payload()["observation"])
    observation["projection_id"] = "enclosure-top-view"
    return _payload(
        lane="mechanical",
        observation=observation,
        proposals=[{"item_id": "comp.u1", "x_mm": 15.2, "y_mm": 13.3, "rotation_deg": 2.0}],
    )


def test_electrical_lane_context_uses_board_and_footprint_geometry() -> None:
    graph = json.loads(GRAPH.read_text(encoding="utf-8"))
    from acd.schema.design_graph import DesignGraph

    electrical = electrical_context(DesignGraph.model_validate(graph), FIXTURE_DIR, FAB_PROFILE)
    assert electrical.context.lane == "electrical"
    assert "U1" in electrical.context.extents
    assert electrical.context.region.x1 == pytest.approx(
        electrical.lane.board.edge_copper_clearance_mm
    )


def test_mechanical_lane_context_uses_the_enclosure_interior() -> None:
    from acd.schema.design_graph import DesignGraph

    graph = DesignGraph.model_validate(json.loads(GRAPH.read_text(encoding="utf-8")))
    context = mechanical_context(graph)
    assert context.lane == "mechanical"
    assert context.keepouts
    assert "comp.u1" in context.extents


def test_cli_reports_electrical_candidates_with_provenance(tmp_path: Path) -> None:
    result = _run_cli(
        tmp_path,
        _electrical_payload(),
        "--fixture-dir",
        str(FIXTURE_DIR),
        "--fab-profile",
        str(FAB_PROFILE),
    )
    assert result.returncode == 0, result.stderr
    report = json.loads((tmp_path / "candidates.json").read_text(encoding="utf-8"))
    assert report["artifact_kind"] == "vision_placement_candidates"
    assert report["pass_evidence"] is False
    assert report["proposed_item_ids"] == ["C1", "U2"]
    assert len(report["candidates"]["vision"]) == len(report["candidates"]["baseline"])
    assert set(report["surrogate_metrics"]) == {"vision", "baseline"}
    provenance = report["provenance"]
    assert provenance["skill_name"] == "acd-placement-search"
    assert provenance["script_name"] == "vision_proposal.py"
    assert provenance["script_sha256"].startswith("sha256:")
    assert provenance["proposal_sha256"].startswith("sha256:")
    assert provenance["relaxation_profile_id"] == "placement-relaxation-default"
    assert provenance["graph_revision"] == "r1"
    assert provenance["observation"]["tool_name"] == "inspect_image_with_vision"
    assert "response" not in provenance["observation"]


def test_cli_is_deterministic(tmp_path: Path) -> None:
    outputs: list[str] = []
    for name in ("first", "second"):
        run_dir = tmp_path / name
        run_dir.mkdir()
        result = _run_cli(
            run_dir,
            _electrical_payload(),
            "--fixture-dir",
            str(FIXTURE_DIR),
            "--fab-profile",
            str(FAB_PROFILE),
        )
        assert result.returncode == 0, result.stderr
        outputs.append((run_dir / "candidates.json").read_text(encoding="utf-8"))
    assert outputs[0] == outputs[1]


def test_cli_reports_mechanical_candidates(tmp_path: Path) -> None:
    result = _run_cli(tmp_path, _mechanical_payload())
    assert result.returncode == 0, result.stderr
    report = json.loads((tmp_path / "candidates.json").read_text(encoding="utf-8"))
    assert report["lane"] == "mechanical"
    assert [item["item_id"] for item in report["candidates"]["vision"]] == ["comp.u1"]
    assert report["candidates"]["baseline"][0]["item_id"] == "comp.u1"
    assert report["surrogate_metrics"] == {}


def test_cli_fails_closed_without_the_electrical_lane_inputs(tmp_path: Path) -> None:
    result = _run_cli(tmp_path, _electrical_payload())
    assert result.returncode != 0
    assert "requires --fixture-dir and --fab-profile" in result.stderr
    assert not (tmp_path / "candidates.json").exists()


def test_cli_fails_closed_on_an_evidence_claiming_proposal(tmp_path: Path) -> None:
    payload = _electrical_payload()
    payload["pass_evidence"] = True
    result = _run_cli(
        tmp_path,
        payload,
        "--fixture-dir",
        str(FIXTURE_DIR),
        "--fab-profile",
        str(FAB_PROFILE),
    )
    assert result.returncode != 0
    assert "pass_evidence" in result.stderr
    assert not (tmp_path / "candidates.json").exists()
