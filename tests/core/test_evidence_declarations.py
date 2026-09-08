"""Tests for declared-evidence resolution against measured records."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from acd.core.evidence_declarations import (
    check_cpl_rotation_record,
    check_fab_profile_declaration,
    collect_evidence_declaration_findings,
    cpl_rotation_record_path,
)
from acd.pipeline.repository import repository_root
from acd.schema.design_graph import AttrValue, DesignGraph, GraphNode

FIXTURE = Path("fixtures/golden-design-1/graph.json")
PROFILES = Path("profiles")


def _graph(*nodes: GraphNode) -> DesignGraph:
    return DesignGraph(graph_id="demo-design", revision="r1", nodes=list(nodes))


def _component(
    node_id: str = "comp.u9",
    *,
    refdes: str = "U9",
    basis: str = "confirmed",
    lcsc: str | None = "C9999",
) -> GraphNode:
    attrs: dict[str, AttrValue] = {
        "refdes": refdes,
        "cpl_rotation_evidence_basis": basis,
    }
    if lcsc is not None:
        attrs["lcsc"] = lcsc
    return GraphNode(id=node_id, kind="electrical.component", attrs=attrs)


def _intent(**attrs: str) -> GraphNode:
    base: dict[str, AttrValue] = {
        "fab_profile": "jlcpcb-fr4-2l-1oz",
        "profile_source": "https://jlcpcb.com/capabilities/pcb-assembly-capabilities",
        "profile_fetched_at": "2026-08-11T00:00:00Z",
    }
    base.update(attrs)
    return GraphNode(id="fab.order_intent", kind="fab.order_intent", attrs=base)


def _record(path: Path, *, refdes: str, lcsc: str, response: dict[str, object]) -> None:
    canonical = json.dumps(
        response, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    record = {
        "schema_version": "0.1",
        "refdes": refdes,
        "lcsc": lcsc,
        "url": "https://easyeda.com/api/products/x",
        "retrieved_at": "2026-08-13T00:00:00Z",
        "response_sha256": "sha256:" + "0" * 64,
        "response_canonical_sha256": f"sha256:{hashlib.sha256(canonical).hexdigest()}",
        "response": response,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record), encoding="utf-8")


def _profiles_root(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "profiles").mkdir(parents=True)
    for child in PROFILES.iterdir():
        target = root / "profiles" / child.name
        if child.is_dir():
            shutil.copytree(child, target)
        else:
            shutil.copy2(child, target)
    return root


def test_gd1_fixture_resolves_all_declared_evidence() -> None:
    graph = DesignGraph.model_validate_json(FIXTURE.read_text(encoding="utf-8"))
    findings = collect_evidence_declaration_findings(graph, root=repository_root())
    assert findings == []


def test_confirmed_component_without_record_is_unverified(tmp_path: Path) -> None:
    graph = _graph(_component())
    findings = collect_evidence_declaration_findings(graph, root=tmp_path)
    assert len(findings) == 1
    finding = findings[0]
    assert finding.code == "evidence.cpl_rotation.declared_unverified"
    assert finding.attr == "cpl_rotation_evidence_basis"
    assert "demo-design-cpl-orientation/U9.json" in finding.detail
    assert "fetch_lcsc_footprint_orientation.py" in finding.detail


def test_wrong_record_hash_is_unverified(tmp_path: Path) -> None:
    path = cpl_rotation_record_path(tmp_path, "demo-design", "U9")
    _record(path, refdes="U9", lcsc="C9999", response={"result": {"x": 1}})
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["response_canonical_sha256"] = "sha256:" + "f" * 64
    path.write_text(json.dumps(payload), encoding="utf-8")
    findings = collect_evidence_declaration_findings(_graph(_component()), root=tmp_path)
    assert len(findings) == 1
    assert "hash" in findings[0].detail


def test_record_lcsc_mismatch_is_unverified(tmp_path: Path) -> None:
    path = cpl_rotation_record_path(tmp_path, "demo-design", "U9")
    _record(path, refdes="U9", lcsc="C1111", response={"result": {"x": 1}})
    findings = collect_evidence_declaration_findings(_graph(_component()), root=tmp_path)
    assert len(findings) == 1
    assert "lcsc" in findings[0].detail


def test_estimated_basis_needs_no_record(tmp_path: Path) -> None:
    graph = _graph(_component(basis="estimated"))
    assert collect_evidence_declaration_findings(graph, root=tmp_path) == []


def test_resolved_record_produces_no_finding(tmp_path: Path) -> None:
    path = cpl_rotation_record_path(tmp_path, "demo-design", "U9")
    _record(path, refdes="U9", lcsc="C9999", response={"result": {"x": 1}})
    assert collect_evidence_declaration_findings(_graph(_component()), root=tmp_path) == []


def test_check_cpl_rotation_record_variants(tmp_path: Path) -> None:
    path = tmp_path / "missing.json"
    assert "missing" in (check_cpl_rotation_record(path, refdes="R1", lcsc=None) or "")
    path.write_text("not json", encoding="utf-8")
    assert check_cpl_rotation_record(path, refdes="R1", lcsc=None) is not None
    _record(path, refdes="R1", lcsc="C1", response={"a": 1})
    assert check_cpl_rotation_record(path, refdes="R2", lcsc=None) is not None
    assert check_cpl_rotation_record(path, refdes="R1", lcsc=None) is None


def test_fab_profile_fetched_at_mismatch_is_unverified(tmp_path: Path) -> None:
    root = _profiles_root(tmp_path)
    graph = _graph(_intent(profile_fetched_at="1999-01-01T00:00:00Z"))
    findings = collect_evidence_declaration_findings(graph, root=root)
    assert len(findings) == 1
    assert findings[0].code == "evidence.fab_profile.declared_unverified"
    assert findings[0].attr == "profile_fetched_at"
    assert "profile_source" in findings[0].detail


def test_unknown_fab_profile_is_unverified_not_raised(tmp_path: Path) -> None:
    root = _profiles_root(tmp_path)
    graph = _graph(_intent(fab_profile="no-such-profile"))
    findings = collect_evidence_declaration_findings(graph, root=root)
    assert len(findings) == 1
    assert findings[0].attr == "fab_profile"


def test_fab_profile_declaration_resolves(tmp_path: Path) -> None:
    root = _profiles_root(tmp_path)
    graph = _graph(_intent())
    assert collect_evidence_declaration_findings(graph, root=root) == []


def test_check_fab_profile_declaration_direct() -> None:
    sources = [{"url": "https://example.test/a", "fetched_at": "2026-01-01T00:00:00Z"}]
    assert (
        check_fab_profile_declaration(
            fab_profile="p",
            profile_source="https://example.test/a",
            profile_fetched_at="2026-01-01T00:00:00Z",
            sources=sources,
        )
        is None
    )
    reason = check_fab_profile_declaration(
        fab_profile="p",
        profile_source="https://example.test/a",
        profile_fetched_at="2026-02-02T00:00:00Z",
        sources=sources,
    )
    assert reason is not None and "2026-01-01" in reason


def test_value_error_text_for_unresolved_provenance() -> None:
    reason = check_fab_profile_declaration(
        fab_profile="p",
        profile_source="u",
        profile_fetched_at="t",
        sources=[],
    )
    assert reason is not None
    message = (
        "fab.order_intent provenance does not resolve to the loaded fab "
        f"profile: {reason}"
    )
    assert "does not resolve" in message
