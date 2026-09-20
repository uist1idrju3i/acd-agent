"""Mechanical DFM gate regression tests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from acd.adapters.cad import mechanical_dfm
from acd.adapters.cad.mechanical_dfm import (
    MechanicalDfmFinding,
    check_mechanical_dfm,
)
from acd.adapters.cad.project import build_enclosure_shapes
from acd.core.electrical.electrical import GraphExtractionError
from acd.core.mechanical.mechanical import extract_mechanical_lane
from acd.schema.design_graph import DesignGraph

FIXTURE = Path(__file__).parents[3] / "fixtures/mechanism-library/graph.json"


def _graph(**updates: object) -> DesignGraph:
    graph = DesignGraph.model_validate_json(FIXTURE.read_text(encoding="utf-8"))
    enclosure = next(node for node in graph.nodes if node.kind == "mechanical.enclosure")
    attrs = {**enclosure.attrs, **updates}
    replacement = enclosure.model_copy(update={"attrs": attrs})
    return graph.model_copy(
        update={
            "nodes": [
                replacement if node.id == enclosure.id else node for node in graph.nodes
            ]
        }
    )


def _findings(graph: DesignGraph) -> tuple[MechanicalDfmFinding, ...]:
    lane = extract_mechanical_lane(graph)
    shell, lid = build_enclosure_shapes(lane)
    return check_mechanical_dfm(lane, (shell, lid))


def _status(findings: tuple[MechanicalDfmFinding, ...]) -> str:
    statuses = {item.status for item in findings}
    if not statuses:
        return "not_applicable"
    if "fail" in statuses:
        return "fail"
    if "unknown" in statuses:
        return "unknown"
    return "pass"


def test_mechanism_fixture_fdm_dfm_passes() -> None:
    findings = _findings(
        DesignGraph.model_validate_json(FIXTURE.read_text(encoding="utf-8"))
    )
    assert _status(findings) == "pass"
    assert next(item for item in findings if item.rule_id == "min_wall").measured == 2.0


def test_missing_manufacturing_process_is_not_applicable() -> None:
    assert _findings(_graph(manufacturing_process=None, dfm_profile=None)) == ()


def test_injection_variant_reports_vertical_wall_draft() -> None:
    findings = _findings(
        _graph(
            manufacturing_process="injection_molding",
            dfm_profile={
                "min_wall_mm": 0.7,
                "max_wall_mm": 100.0,
                "min_draft_deg": 0.5,
                "max_thickness_ratio": 100.0,
                "parting_plane": "xy_top",
                "min_feature_mm": 0.5,
            },
        )
    )
    draft = [item for item in findings if item.rule_id == "draft" and item.status == "fail"]
    assert draft
    assert all(item.face_center_mm is not None for item in draft)


def test_dfm_negative_profiles_fail() -> None:
    thin = _findings(_graph(dfm_profile={
        "min_wall_mm": 3.0,
        "max_overhang_deg": 180.0,
        "min_feature_mm": 0.5,
        "nozzle_diameter_mm": 0.4,
    }))
    overhang = _findings(_graph(dfm_profile={
        "min_wall_mm": 0.7,
        "max_overhang_deg": 0.1,
        "min_feature_mm": 0.5,
        "nozzle_diameter_mm": 0.4,
    }))
    assert _status(thin) == "fail"
    assert _status(overhang) == "fail"
    assert any(item.rule_id == "overhang" for item in overhang)


def test_sla_drain_hole_required_fails_when_absent() -> None:
    findings = _findings(
        _graph(
            manufacturing_process="sla",
            dfm_profile={
                "min_wall_mm": 0.7,
                "max_unsupported_overhang_deg": 180.0,
                "min_feature_mm": 0.5,
                "drain_hole_required": True,
            },
        )
    )
    assert any(item.rule_id == "drain_hole" and item.status == "fail" for item in findings)


def test_missing_profile_is_unknown_and_invalid_process_raises() -> None:
    assert _status(_findings(_graph(dfm_profile=None))) == "unknown"
    with pytest.raises(GraphExtractionError):
        extract_mechanical_lane(_graph(manufacturing_process="laser_cut"))


def test_measurement_error_is_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_measurement_error(
        *args: object, **kwargs: object
    ) -> list[MechanicalDfmFinding]:
        raise RuntimeError("face error")

    monkeypatch.setattr(mechanical_dfm, "_check_min_wall", raise_measurement_error)
    findings = _findings(
        DesignGraph.model_validate_json(FIXTURE.read_text(encoding="utf-8"))
    )
    assert _status(findings) == "unknown"
    assert findings[0].rule_id == "dfm_evaluation"


def test_dfm_report_is_deterministic() -> None:
    graph = DesignGraph.model_validate_json(FIXTURE.read_text(encoding="utf-8"))
    payloads: list[list[dict[str, object]]] = []
    for _ in range(2):
        payloads.append(
            [
                {
                    "rule_id": item.rule_id,
                    "status": item.status,
                    "measured": item.measured,
                    "limit": item.limit,
                    "face_center_mm": item.face_center_mm,
                    "feature_id": item.feature_id,
                }
                for item in _findings(graph)
            ]
        )
    encoded = [
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        for payload in payloads
    ]
    assert hashlib.sha256(encoded[0]).digest() == hashlib.sha256(encoded[1]).digest()
