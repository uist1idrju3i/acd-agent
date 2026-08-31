from __future__ import annotations

# pyright: reportPrivateUsage=false,reportUnknownArgumentType=false,reportUnknownLambdaType=false,reportUnknownVariableType=false,reportUnknownMemberType=false
import json
import shutil
from pathlib import Path

import pytest

import acd.core.exploration as exploration
from acd.core.design_predicates import PREDICATE_CATALOG, PredicateResult
from acd.core.electrical import ElectricalLane
from acd.core.exploration import (
    ExplorationCandidate,
    ExplorationError,
    enumerate_gpio_assignment_candidates,
    explore_board_candidates,
)
from acd.schema.common import canonical_json_sha256
from acd.schema.design_graph import DesignGraph, GraphNode

FIXTURE_DIR = Path("fixtures/golden-design-1")
GRAPH_PATH = FIXTURE_DIR / "graph.json"


def _graph() -> DesignGraph:
    return DesignGraph.model_validate_json(GRAPH_PATH.read_text(encoding="utf-8"))


def _number_attr(node: GraphNode, key: str) -> float:
    attrs = node.attrs
    value = attrs[key]
    assert isinstance(value, int | float) and not isinstance(value, bool)
    return float(value)


def _passing_pre_router(
    _graph: DesignGraph, _lane: ElectricalLane, _fixture_dir: Path
) -> tuple[PredicateResult, ...]:
    return tuple(
        PredicateResult(name=name, status="pass", detail="test pre-router pass")
        for name in PREDICATE_CATALOG
    )


def _placement_candidate(graph: DesignGraph) -> ExplorationCandidate:
    placements = {
        str(node.attrs["refdes"]): {
            "x_mm": _number_attr(node, "placement_x_mm"),
            "y_mm": _number_attr(node, "placement_y_mm"),
            "rotation_deg": _number_attr(node, "placement_rotation_deg"),
        }
        for node in graph.nodes
        if node.kind == "electrical.component"
    }
    return ExplorationCandidate(
        candidate_id="placement-0001",
        kind="placement",
        dimensions=("component_placement_xy", "component_rotation_deg"),
        changes={"placements": placements},
        provenance={
            "skill_name": "acd-placement-search",
            "script_name": "placement_search.py",
            "script_sha256": "sha256:test",
            "graph_revision": graph.revision,
            "pass_evidence": False,
        },
    )


def test_gpio_candidates_are_deterministic_and_strapping_pruned() -> None:
    first = enumerate_gpio_assignment_candidates(_graph())
    second = enumerate_gpio_assignment_candidates(_graph())

    assert [candidate.candidate_id for candidate in first] == [
        candidate.candidate_id for candidate in second
    ]
    assert [candidate.changes for candidate in first] == [candidate.changes for candidate in second]
    led_targets = {
        values["gpio"]
        for candidate in first
        for node_id, values in candidate.changes.items()
        if node_id == "fw.pin.led"
    }
    assert led_targets.isdisjoint({2, 8, 9})


def test_unknown_and_non_explorable_dimensions_fail_closed() -> None:
    with pytest.raises(ExplorationError, match="unknown change dimensions"):
        exploration._validate_dimensions(("not_declared",), {"component_placement_xy": True})
    with pytest.raises(ExplorationError, match="non-explorable"):
        exploration._validate_dimensions(("copper_layer_count",), {"copper_layer_count": False})


def test_malformed_skill_output_fails_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    graph = _graph()
    def fake_run(*args: object, **kwargs: object) -> object:
        command = args[0]
        assert isinstance(command, tuple)
        Path(str(command[-1])).parent.mkdir(parents=True, exist_ok=True)
        Path(str(command[-1])).write_text("{}", encoding="utf-8")
        return type("Completed", (), {"returncode": 0, "stderr": ""})()

    monkeypatch.setattr(exploration.subprocess, "run", fake_run)
    with pytest.raises(ExplorationError, match="must be an array"):
        exploration._placement_candidates(GRAPH_PATH, FIXTURE_DIR, tmp_path, graph)


def test_missing_skill_script_fails_closed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    graph = _graph()
    monkeypatch.setattr(exploration, "PLACEMENT_SCRIPT", "missing/placement_search.py")
    with pytest.raises(ExplorationError, match="script is missing"):
        exploration._placement_candidates(GRAPH_PATH, FIXTURE_DIR, tmp_path, graph)


def test_budget_exhaustion_is_fail_closed_and_preserves_source(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    graph = _graph()
    source_fixture = tmp_path / "fixture"
    shutil.copytree(FIXTURE_DIR, source_fixture)
    source_graph = source_fixture / "graph.json"
    source_graph.write_text(GRAPH_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    before = source_graph.read_bytes()
    monkeypatch.setattr(
        exploration,
        "_placement_candidates",
        lambda *_args: (_placement_candidate(graph),),
    )

    def reject(_fixture: Path, _out: Path) -> None:
        raise RuntimeError("router rejected candidate")

    result = explore_board_candidates(
        source_graph,
        source_fixture,
        tmp_path / "out",
        max_candidates=1,
        pipeline_runner=reject,
    )

    assert result.report["status"] == "exhausted"
    assert result.report["pass_evidence"] is False
    assert source_graph.read_bytes() == before
    assert json.loads(result.report_path.read_text(encoding="utf-8"))["content_sha256"]


def test_max_passes_is_forwarded_to_default_pipeline_runner(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    graph = _graph()
    source_fixture = tmp_path / "fixture"
    shutil.copytree(FIXTURE_DIR, source_fixture)
    source_graph = source_fixture / "graph.json"
    source_graph.write_text(GRAPH_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(
        exploration,
        "_placement_candidates",
        lambda *_args: (_placement_candidate(graph),),
    )
    monkeypatch.setattr(exploration, "evaluate_design_predicates", _passing_pre_router)
    calls: list[int] = []

    def fake_run_pipeline(
        _fixture: Path, _out: Path, *, max_passes: int
    ) -> dict[str, str]:
        calls.append(max_passes)
        return {}

    monkeypatch.setattr("acd.pipeline.gd1_board.run_pipeline", fake_run_pipeline)
    result = explore_board_candidates(
        source_graph,
        source_fixture,
        tmp_path / "out",
        max_candidates=1,
        max_passes=7,
    )

    assert result.report["status"] == "candidate_found"
    assert result.report["max_passes"] == 7
    assert calls == [7]


def test_max_passes_must_be_positive(tmp_path: Path) -> None:
    with pytest.raises(ExplorationError, match="max_passes must be positive"):
        explore_board_candidates(
            GRAPH_PATH,
            FIXTURE_DIR,
            tmp_path / "out",
            max_candidates=1,
            max_passes=0,
        )


def test_successful_candidate_is_observation_and_writes_only_final_winner(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    graph = _graph()
    source_fixture = tmp_path / "fixture"
    shutil.copytree(FIXTURE_DIR, source_fixture)
    source_graph = source_fixture / "graph.json"
    source_graph.write_text(GRAPH_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(
        exploration,
        "_placement_candidates",
        lambda *_args: (_placement_candidate(graph),),
    )
    monkeypatch.setattr(exploration, "evaluate_design_predicates", _passing_pre_router)

    result = explore_board_candidates(
        source_graph,
        source_fixture,
        tmp_path / "out",
        max_candidates=1,
        dry_run=True,
        pipeline_runner=lambda _fixture, _out: {"gate": "completed"},
    )

    assert result.report["status"] == "candidate_found"
    assert result.report["pass_evidence"] is False
    assert result.report["winner_written"] is False
    assert all(
        candidate["provenance"]["pass_evidence"] is False
        for candidate in result.report["candidates"]
    )


def test_successful_candidate_preserves_revision_and_changes_graph_content(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    graph = _graph()
    source_fixture = tmp_path / "fixture"
    shutil.copytree(FIXTURE_DIR, source_fixture)
    source_graph = source_fixture / "graph.json"
    source_graph.write_text(GRAPH_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    before = DesignGraph.model_validate_json(source_graph.read_text(encoding="utf-8"))
    before_hash = canonical_json_sha256(before.model_dump(mode="json"))
    monkeypatch.setattr(
        exploration,
        "_placement_candidates",
        lambda *_args: (_placement_candidate(graph),),
    )
    monkeypatch.setattr(exploration, "evaluate_design_predicates", _passing_pre_router)

    result = explore_board_candidates(
        source_graph,
        source_fixture,
        tmp_path / "out",
        max_candidates=1,
        pipeline_runner=lambda _fixture, _out: {"gate": "completed"},
    )

    after = DesignGraph.model_validate_json(source_graph.read_text(encoding="utf-8"))
    after_hash = canonical_json_sha256(after.model_dump(mode="json"))
    assert result.report["status"] == "candidate_found"
    assert result.report["winner_written"] is True
    assert after.graph_id == before.graph_id
    assert after.revision == before.revision
    assert after_hash != before_hash
    assert result.report["target_revision"] == after.revision


def test_malformed_gate_evidence_stops_exploration(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    graph = _graph()
    source_fixture = tmp_path / "fixture"
    shutil.copytree(FIXTURE_DIR, source_fixture)
    source_graph = source_fixture / "graph.json"
    monkeypatch.setattr(
        exploration,
        "_placement_candidates",
        lambda *_args: (_placement_candidate(graph),),
    )
    monkeypatch.setattr(exploration, "evaluate_design_predicates", _passing_pre_router)

    def reject_with_bad_evidence(_fixture: Path, output: Path) -> None:
        evidence = output / "gate-evidence" / "design-predicates.json"
        evidence.parent.mkdir(parents=True)
        evidence.write_text("[", encoding="utf-8")
        raise RuntimeError("gate rejected candidate")

    result = explore_board_candidates(
        source_graph,
        source_fixture,
        tmp_path / "out",
        max_candidates=1,
        pipeline_runner=reject_with_bad_evidence,
    )

    assert result.report["status"] == "stopped"
    assert result.report["candidates"][0]["outcome"]["status"] == "stopped"

def _remediation_evidence(
    tmp_path: Path,
    *,
    revision: str = "r1",
    predicates: list[dict[str, object]] | None = None,
    valid_hash: bool = True,
) -> Path:
    payload: dict[str, object] = {
        "artifact_kind": "design_predicate_report",
        "gate": "design_predicates",
        "target_revision": revision,
        "observation": {
            "predicates": predicates
            if predicates is not None
            else [
                {
                    "name": "power_decoupling",
                    "status": "fail",
                    "remediation": {
                        "change_dimensions": ["component_placement_xy"],
                        "subject": {"refdes": "C5", "target_refdes": "U1"},
                    },
                }
            ]
        },
    }
    path = tmp_path / "design-predicates.json"
    path.write_text(
        json.dumps(
            {
                **payload,
                "content_sha256": canonical_json_sha256(payload)
                if valid_hash
                else "sha256:" + "0" * 64,
            }
        ),
        encoding="utf-8",
    )
    return path


def test_declared_remediation_is_extracted_from_hashed_evidence(tmp_path: Path) -> None:
    requests = exploration.load_remediation_requests(
        _remediation_evidence(tmp_path), "r1"
    )

    assert [item.predicate for item in requests] == ["power_decoupling"]
    assert requests[0].change_dimensions == ("component_placement_xy",)
    assert requests[0].refdes == "C5"
    assert requests[0].target_refdes == "U1"


def test_predicates_without_remediation_declare_no_requests(tmp_path: Path) -> None:
    evidence = _remediation_evidence(
        tmp_path,
        predicates=[{"name": "power_decoupling", "status": "fail"}],
    )

    assert exploration.load_remediation_requests(evidence, "r1") == ()


def test_missing_remediation_evidence_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(ExplorationError, match="is missing"):
        exploration.load_remediation_requests(tmp_path / "absent.json", "r1")


def test_remediation_evidence_revision_mismatch_fails_closed(tmp_path: Path) -> None:
    evidence = _remediation_evidence(tmp_path, revision="r1")

    with pytest.raises(ExplorationError, match="revision does not match"):
        exploration.load_remediation_requests(evidence, "r2")


def test_remediation_evidence_hash_mismatch_fails_closed(tmp_path: Path) -> None:
    evidence = _remediation_evidence(tmp_path, valid_hash=False)

    with pytest.raises(ExplorationError, match="content hash is invalid"):
        exploration.load_remediation_requests(evidence, "r1")


def test_malformed_remediation_dimensions_fail_closed(tmp_path: Path) -> None:
    evidence = _remediation_evidence(
        tmp_path,
        predicates=[
            {
                "name": "power_decoupling",
                "status": "fail",
                "remediation": {"change_dimensions": [3], "subject": {"refdes": "C5"}},
            }
        ],
    )

    with pytest.raises(ExplorationError, match="dimensions are malformed"):
        exploration.load_remediation_requests(evidence, "r1")
