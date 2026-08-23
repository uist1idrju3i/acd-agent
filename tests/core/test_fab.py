from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from acd.core.electrical import GraphExtractionError, extract_electrical_lane
from acd.core.fab import (
    extract_fab_intent,
    load_fab_profile,
    load_fab_profile_by_id,
    load_fab_profile_registry,
    resolve_fab_profile_path,
    validate_allowances_against_profile,
)
from acd.schema import DesignGraph

ROOT = Path(__file__).resolve().parents[2]
PROFILE = ROOT / "profiles/jlcpcb/fab-profile-jlcpcb-fr4-2l-1oz.json"
ProfileMutation = Callable[[dict[str, Any]], None]


def _add_unknown_key(data: dict[str, Any]) -> None:
    data["unexpected"] = True


def _set_invalid_position_basis(data: dict[str, Any]) -> None:
    data["cpl_contract"]["position_basis"] = "unknown"


def _add_source_index(data: dict[str, Any]) -> None:
    data["sources"][0]["source_index"] = 0


def _graph(
    intent_attrs: dict[str, Any] | None = None,
    extras: list[dict[str, Any]] | None = None,
) -> DesignGraph:
    attrs: dict[str, Any] = {
        "fab_profile": "jlcpcb-fr4-2l-1oz",
        "profile_source": "https://jlcpcb.com/capabilities/pcb-assembly-capabilities",
        "profile_fetched_at": "2026-08-11T00:00:00Z",
        "pcba_class_target": "economic",
        "quantity_pcs": 5,
        "delivery_format": "single",
        "soldermask_color": "green",
        "surface_finish": "HASL",
        "assembly_sides": "top",
    }
    attrs.update(intent_attrs or {})
    nodes: list[dict[str, object]] = [
        {"id": "req.test", "kind": "requirement", "attrs": {"text": "test"}},
        {
            "id": "fab.intent",
            "kind": "fab.order_intent",
            "attrs": attrs,
            "depends_on": ["req.test"],
        },
    ]
    nodes.extend(extras or [])
    return DesignGraph.model_validate({"graph_id": "test", "revision": "r1", "nodes": nodes})


def test_profile_schema_and_provenance() -> None:
    profile = load_fab_profile(PROFILE)
    assert profile.profile_id == "jlcpcb-fr4-2l-1oz"
    assert len(profile.preference_rule_ids) == len(profile.data["preferences"])
    assert {source["fetched_at"] for source in profile.data["sources"]} == {
        "2026-08-11T00:00:00Z",
        "2026-08-13T00:00:00Z",
    }
    json.dumps(profile.data)


@pytest.mark.parametrize(
    ("change", "match"),
    [
        (_add_unknown_key, "unexpected"),
        (_set_invalid_position_basis, "position_basis"),
        (_add_source_index, "source_index"),
    ],
)
def test_invalid_profile_fails_closed(
    change: ProfileMutation, match: str, tmp_path: Path
) -> None:
    data = json.loads(PROFILE.read_text(encoding="utf-8"))
    change(data)
    path = tmp_path / "invalid-profile.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValidationError, match=match):
        load_fab_profile(path)


def test_economic_combinations_are_complete() -> None:
    profile = load_fab_profile(PROFILE)
    combinations = profile.data["assembly_classes"]["economic"]["combinations"]
    assert len(combinations) == 11
    assert profile.data["assembly_classes"]["standard"]["build_time_days"] == {"min": 4}
    assert profile.data["assembly_classes"]["standard"]["thickness_mm"] == [
        0.4,
        0.6,
        0.8,
        1.0,
        1.2,
        1.6,
        2.0,
    ]
    assert "preferred_track_width" not in profile.data["capabilities"]


@pytest.mark.parametrize(
    "attrs",
    [{"pcba_class_target": "invalid"}, {"quantity_pcs": "5"}, {"surface_finish": ""}],
)
def test_fab_intent_fails_closed(attrs: dict[str, object]) -> None:
    with pytest.raises((ValueError, GraphExtractionError)):
        extract_fab_intent(_graph(attrs))


def test_allowance_requires_requirement_and_known_rule() -> None:
    bad_ref = {
        "id": "fab.allowance",
        "kind": "fab.process_allowance",
        "attrs": {
            "rule_id": "via-in-pad-process",
            "reason": "BGA requirement",
            "requirement": "req.missing",
            "impact_accepted": ["cost", "quality"],
        },
    }
    with pytest.raises(GraphExtractionError, match="requirement"):
        extract_fab_intent(_graph(extras=[bad_ref]))
    good = {
        "id": "fab.allowance",
        "kind": "fab.process_allowance",
        "attrs": {
            "rule_id": "not-in-profile",
            "reason": "test",
            "requirement": "req.test",
            "impact_accepted": ["cost"],
        },
        "depends_on": ["req.test"],
    }
    intent, allowances = extract_fab_intent(_graph(extras=[good]))
    assert intent.pcba_class_target == "economic"
    with pytest.raises(GraphExtractionError, match="unknown"):
        validate_allowances_against_profile(allowances, load_fab_profile(PROFILE))


def test_component_assembly_is_required() -> None:
    graph_path = ROOT / "fixtures/golden-design-1/graph.json"
    data = json.loads(graph_path.read_text(encoding="utf-8"))
    component = next(node for node in data["nodes"] if node["kind"] == "electrical.component")
    del component["attrs"]["assembly"]
    with pytest.raises(GraphExtractionError, match="assembly"):
        extract_electrical_lane(DesignGraph.model_validate(data))


def test_fab_profile_registry_resolves_registered_profile() -> None:
    registry = load_fab_profile_registry()
    assert resolve_fab_profile_path("jlcpcb-fr4-2l-1oz", registry) == PROFILE
    assert load_fab_profile_by_id("jlcpcb-fr4-2l-1oz", registry).profile_id == (
        "jlcpcb-fr4-2l-1oz"
    )


def test_fab_profile_registry_supports_two_profile_selection(tmp_path: Path) -> None:
    first = json.loads(PROFILE.read_text(encoding="utf-8"))
    second = json.loads(PROFILE.read_text(encoding="utf-8"))
    second["profile_id"] = "jlcpcb-fr4-2l-1oz-alt"
    first_path = tmp_path / "first.json"
    second_path = tmp_path / "second.json"
    first_path.write_text(json.dumps(first), encoding="utf-8")
    second_path.write_text(json.dumps(second), encoding="utf-8")
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "registry_id": "test-fab-registry",
                "profiles": [
                    {
                        "profile_id": first["profile_id"],
                        "path": first_path.name,
                        "fab": first["fab"],
                        "process": first["process"],
                    },
                    {
                        "profile_id": second["profile_id"],
                        "path": second_path.name,
                        "fab": second["fab"],
                        "process": second["process"],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    registry = load_fab_profile_registry(registry_path)
    assert load_fab_profile_by_id("jlcpcb-fr4-2l-1oz-alt", registry).profile_id == (
        "jlcpcb-fr4-2l-1oz-alt"
    )


@pytest.mark.parametrize("profile_id", ["missing-profile", ""])
def test_unknown_fab_profile_id_fails_closed(profile_id: str) -> None:
    with pytest.raises(ValueError):
        resolve_fab_profile_path(profile_id)


def test_fab_profile_registry_detects_metadata_mismatch(tmp_path: Path) -> None:
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "registry_id": "test-fab-registry",
                "profiles": [
                    {
                        "profile_id": "jlcpcb-fr4-2l-1oz",
                        "path": str(PROFILE),
                        "fab": "wrong-fab",
                        "process": "rigid-fr4",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="metadata mismatch"):
        resolve_fab_profile_path(
            "jlcpcb-fr4-2l-1oz",
            load_fab_profile_registry(registry_path),
        )


def test_fab_profile_registry_detects_missing_path(tmp_path: Path) -> None:
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "registry_id": "test-fab-registry",
                "profiles": [
                    {
                        "profile_id": "missing-profile",
                        "path": "missing.json",
                        "fab": "fab",
                        "process": "process",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="does not exist"):
        resolve_fab_profile_path(
            "missing-profile",
            load_fab_profile_registry(registry_path),
        )
