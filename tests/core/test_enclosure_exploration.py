from __future__ import annotations

import hashlib
import json
import shutil
from itertools import pairwise
from pathlib import Path

import pytest

import acd.core.enclosure_exploration as enclosure_exploration
from acd.adapters.cad.mechanical import MechanicalGateError
from acd.core.design_freedom import (
    DesignFreedomDeclaration,
    load_design_freedom_declaration,
)
from acd.core.enclosure_exploration import (
    EnclosureExplorationError,
    enumerate_enclosure_candidates,
    explore_enclosure_candidates,
    validate_enclosure_dimensions,
)
from acd.schema.design_graph import DesignGraph

FIXTURE_DIR = Path("fixtures/golden-design-1")
GRAPH_PATH = FIXTURE_DIR / "graph.json"


def _graph() -> DesignGraph:
    return DesignGraph.model_validate_json(GRAPH_PATH.read_text(encoding="utf-8"))


def test_enclosure_candidates_are_deterministic() -> None:
    first = enumerate_enclosure_candidates(_graph())
    second = enumerate_enclosure_candidates(_graph())

    assert [candidate.candidate_id for candidate in first] == [
        candidate.candidate_id for candidate in second
    ]
    assert [candidate.changes for candidate in first] == [
        candidate.changes for candidate in second
    ]
    assert first[0].provenance["declaration_id"]
    assert first[0].provenance["declaration_hash"].startswith("sha256:")
    script_path = Path(enclosure_exploration.__file__).resolve()
    expected_script_hash = "sha256:" + hashlib.sha256(script_path.read_bytes()).hexdigest()
    assert first[0].provenance["script_sha256"] == expected_script_hash
    assert all(
        set(candidate.changes) == set(candidate.dimensions)
        and all(value >= 1.0 for value in candidate.changes.values())
        for candidate in first
    )
    assert {dimension for candidate in first for dimension in candidate.dimensions} == {
        "enclosure_internal_clearance_mm",
        "enclosure_standoff_height_mm",
        "enclosure_standoff_radius_mm",
        "enclosure_wall_thickness_mm",
    }


def test_candidates_prioritize_smallest_change_and_support_sampling_density() -> None:
    graph = _graph()
    node = next(item for item in graph.nodes if item.kind == "mechanical.enclosure")
    candidates = enumerate_enclosure_candidates(
        graph,
        ("enclosure_wall_thickness_mm",),
        sampling_points=5,
    )

    expected_values = (1.9, 2.6, 1.2, 3.3, 4.0)
    actual_values = tuple(
        candidate.changes["enclosure_wall_thickness_mm"] for candidate in candidates
    )
    assert actual_values == pytest.approx(expected_values)
    raw_current = node.attrs["wall_thickness_mm"]
    assert isinstance(raw_current, (float, int))
    current = float(raw_current)
    assert all(
        abs(previous.changes["enclosure_wall_thickness_mm"] - current)
        <= abs(candidate.changes["enclosure_wall_thickness_mm"] - current)
        for previous, candidate in pairwise(candidates)
    )


def test_unknown_and_disabled_enclosure_dimensions_fail_closed() -> None:
    with pytest.raises(EnclosureExplorationError, match="unknown change dimensions"):
        validate_enclosure_dimensions(("not_declared",))
    with pytest.raises(EnclosureExplorationError, match="non-explorable"):
        validate_enclosure_dimensions(("enclosure_lid_fit_gap_mm",))


def test_searchable_mechanical_dimension_without_mapping_fails_closed() -> None:
    declaration = load_design_freedom_declaration()
    document = declaration.document.model_copy(
        update={
            "dimensions": [
                item.model_copy(update={"search_enabled": True})
                if item.dimension_id == "enclosure_lid_fit_gap_mm"
                else item
                for item in declaration.dimensions
            ]
        }
    )
    custom = DesignFreedomDeclaration(
        document=document,
        declaration_hash=declaration.declaration_hash,
        path=declaration.path,
    )

    with pytest.raises(EnclosureExplorationError, match="no graph attribute mapping"):
        enumerate_enclosure_candidates(_graph(), declaration=custom)


def test_no_searchable_mechanical_declaration_fails_closed() -> None:
    declaration = load_design_freedom_declaration()
    disabled = declaration.document.model_copy(
        update={
            "dimensions": [
                item.model_copy(update={"search_enabled": False})
                if item.lane == "mechanical"
                else item
                for item in declaration.dimensions
            ]
        }
    )
    no_search = declaration.__class__(
        document=disabled,
        declaration_hash=declaration.declaration_hash,
        path=declaration.path,
    )
    with pytest.raises(EnclosureExplorationError, match="no searchable"):
        enumerate_enclosure_candidates(_graph(), declaration=no_search)


def test_enclosure_graph_value_outside_declared_bounds_fails_closed() -> None:
    graph = _graph()
    node = next(item for item in graph.nodes if item.kind == "mechanical.enclosure")
    changed = graph.model_copy(
        update={
            "nodes": [
                item.model_copy(
                    update={"attrs": {**item.attrs, "wall_thickness_mm": 9.0}}
                )
                if item.id == node.id
                else item
                for item in graph.nodes
            ]
        }
    )
    with pytest.raises(EnclosureExplorationError, match="outside declared bounds"):
        enumerate_enclosure_candidates(changed, ("enclosure_wall_thickness_mm",))


def test_exploration_exhaustion_is_fail_closed_and_preserves_source(
    tmp_path: Path,
) -> None:
    source_fixture = tmp_path / "fixture"
    shutil.copytree(FIXTURE_DIR, source_fixture)
    source_graph = source_fixture / "graph.json"
    before = source_graph.read_bytes()

    def reject(_fixture: Path, out: Path) -> None:
        out.mkdir(parents=True, exist_ok=True)
        (out / "evidence-mechanical.json").write_text("must be removed\n")
        raise MechanicalGateError("mechanical gates failed: interference")

    result = explore_enclosure_candidates(
        source_graph,
        source_fixture,
        tmp_path / "out",
        max_candidates=3,
        dimensions=("enclosure_internal_clearance_mm",),
        pipeline_runner=reject,
    )

    assert result.report["status"] == "exhausted"
    assert result.report["pass_evidence"] is False
    assert result.report["winner_written"] is False
    assert source_graph.read_bytes() == before
    assert not (
        tmp_path / "out" / "candidates" / "enclosure-0001" / "evidence-mechanical.json"
    ).exists()
    assert all(
        record["declaration_id"] == result.report["provenance"]["declaration_id"]
        and record["declaration_hash"] == result.report["provenance"]["declaration_hash"]
        and record["pass_evidence"] is False
        for record in result.report["candidates"]
    )


def test_pipeline_execution_failure_stops_fail_closed(tmp_path: Path) -> None:
    source_fixture = tmp_path / "fixture"
    shutil.copytree(FIXTURE_DIR, source_fixture)
    result = explore_enclosure_candidates(
        source_fixture / "graph.json",
        source_fixture,
        tmp_path / "out",
        max_candidates=1,
        dimensions=("enclosure_internal_clearance_mm",),
        pipeline_runner=lambda _fixture, _out: (_ for _ in ()).throw(
            RuntimeError("CAD kernel unavailable")
        ),
    )

    assert result.report["status"] == "stopped"
    assert result.report["candidates"][0]["outcome"]["pass_evidence"] is False


def test_pipeline_failure_removes_candidate_evidence(tmp_path: Path) -> None:
    source_fixture = tmp_path / "fixture"
    shutil.copytree(FIXTURE_DIR, source_fixture)
    output_root = tmp_path / "out"

    def fail_after_writing_evidence(_fixture: Path, out: Path) -> None:
        out.mkdir(parents=True, exist_ok=True)
        (out / "evidence-mechanical.json").write_text("must be removed\n")
        raise RuntimeError("CAD kernel unavailable")

    result = explore_enclosure_candidates(
        source_fixture / "graph.json",
        source_fixture,
        output_root,
        max_candidates=1,
        dimensions=("enclosure_internal_clearance_mm",),
        pipeline_runner=fail_after_writing_evidence,
    )

    assert result.report["status"] == "stopped"
    assert not (
        output_root / "candidates" / "enclosure-0001" / "evidence-mechanical.json"
    ).exists()


def test_successful_candidate_does_not_leave_authoritative_evidence(
    tmp_path: Path,
) -> None:
    source_fixture = tmp_path / "fixture"
    shutil.copytree(FIXTURE_DIR, source_fixture)
    output_root = tmp_path / "out"

    def succeed(_fixture: Path, out: Path) -> dict[str, object]:
        out.mkdir(parents=True, exist_ok=True)
        (out / "evidence-mechanical.json").write_text("must be removed\n")
        return {
            "authoritative": True,
            "measured_max_interference_volume_mm3": 0.0,
        }

    result = explore_enclosure_candidates(
        source_fixture / "graph.json",
        source_fixture,
        output_root,
        max_candidates=1,
        dimensions=("enclosure_internal_clearance_mm",),
        pipeline_runner=succeed,
    )

    assert result.report["status"] == "candidate_found"
    assert result.report["pass_evidence"] is False
    assert not (
        output_root / "candidates" / "enclosure-0001" / "evidence-mechanical.json"
    ).exists()


def test_sequential_and_parallel_reports_have_same_hash(tmp_path: Path) -> None:
    source_fixture = tmp_path / "fixture"
    shutil.copytree(FIXTURE_DIR, source_fixture)

    sequential = explore_enclosure_candidates(
        source_fixture / "graph.json",
        source_fixture,
        tmp_path / "sequential",
        max_candidates=5,
        dimensions=("enclosure_internal_clearance_mm",),
        jobs=1,
        pipeline_runner=lambda _fixture, _out: {},
    )
    parallel = explore_enclosure_candidates(
        source_fixture / "graph.json",
        source_fixture,
        tmp_path / "parallel",
        max_candidates=5,
        dimensions=("enclosure_internal_clearance_mm",),
        jobs=3,
        pipeline_runner=lambda _fixture, _out: {},
    )

    assert sequential.report["content_sha256"] == parallel.report["content_sha256"]
    assert sequential.report["status"] == parallel.report["status"] == "candidate_found"
    assert json.loads(sequential.report_path.read_text(encoding="utf-8"))[
        "content_sha256"
    ] == sequential.report["content_sha256"]
