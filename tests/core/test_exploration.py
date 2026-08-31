from __future__ import annotations

# pyright: reportPrivateUsage=false,reportUnknownArgumentType=false,reportUnknownLambdaType=false,reportUnknownVariableType=false,reportUnknownMemberType=false
import json
import re
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
from acd.core.rationale import RationaleDocument, check_rationale_coverage
from acd.core.runtime_records import RuntimeObservationError
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


def test_placement_variant_count_matches_skill_contract() -> None:
    script = Path("plugins/acd/skills/acd-placement-search/scripts/placement_search.py")
    source = script.read_text(encoding="utf-8")
    match = re.search(r"_SPACING_STEPS_MM\s*=\s*\(([^)]*)\)", source)
    assert match is not None
    assert len([item for item in match.group(1).split(",") if item.strip()]) == (
        exploration.PLACEMENT_SPACING_VARIANTS
    )


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
        output = Path(str(command[command.index("--output") + 1]))
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text("{}", encoding="utf-8")
        return type("Completed", (), {"returncode": 0, "stderr": ""})()

    monkeypatch.setattr(exploration.subprocess, "run", fake_run)
    with pytest.raises(ExplorationError, match="must be an array"):
        exploration._placement_candidates(GRAPH_PATH, FIXTURE_DIR, tmp_path, graph)


def test_placement_variants_are_ordered_and_provenanced(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    graph = _graph()
    placements = _placement_candidate(graph).changes["placements"]
    calls: list[int] = []

    def fake_run(*args: object, **kwargs: object) -> object:
        command = args[0]
        assert isinstance(command, tuple)
        variant = int(command[command.index("--spacing-variant") + 1])
        output = Path(str(command[command.index("--output") + 1]))
        output.parent.mkdir(parents=True, exist_ok=True)
        payload = [
            {
                "refdes": refdes,
                "x_mm": values["x_mm"] + variant,
                "y_mm": values["y_mm"],
                "rotation_deg": values["rotation_deg"],
            }
            for refdes, values in placements.items()
        ]
        output.write_text(json.dumps(payload), encoding="utf-8")
        calls.append(variant)
        return type("Completed", (), {"returncode": 0, "stderr": ""})()

    monkeypatch.setattr(exploration.subprocess, "run", fake_run)
    candidates = exploration._placement_candidates(
        GRAPH_PATH, FIXTURE_DIR, tmp_path, graph, max_variants=3
    )

    assert calls == [0, 1, 2]
    assert [candidate.candidate_id for candidate in candidates] == [
        "placement-0001",
        "placement-0002",
        "placement-0003",
    ]
    assert [
        candidate.provenance["spacing_variant"] for candidate in candidates
    ] == [0, 1, 2]
    assert len({candidate.provenance["proposal_sha256"] for candidate in candidates}) == 3


def test_unavailable_and_duplicate_placement_variants_are_diagnosed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    graph = _graph()
    placements = _placement_candidate(graph).changes["placements"]

    def fake_run(*args: object, **kwargs: object) -> object:
        command = args[0]
        assert isinstance(command, tuple)
        variant = int(command[command.index("--spacing-variant") + 1])
        if variant == 2:
            return type(
                "Completed",
                (),
                {"returncode": 1, "stderr": "component C5 could not be placed\n"},
            )()
        output = Path(str(command[command.index("--output") + 1]))
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(
                [
                    {
                        "refdes": refdes,
                        "x_mm": values["x_mm"],
                        "y_mm": values["y_mm"],
                        "rotation_deg": values["rotation_deg"],
                    }
                    for refdes, values in placements.items()
                ]
            ),
            encoding="utf-8",
        )
        return type("Completed", (), {"returncode": 0, "stderr": ""})()

    diagnostics: list[dict[str, Any]] = []
    monkeypatch.setattr(exploration.subprocess, "run", fake_run)
    candidates = exploration._placement_candidates(
        GRAPH_PATH,
        FIXTURE_DIR,
        tmp_path,
        graph,
        max_variants=3,
        diagnostics=diagnostics,
    )

    assert [candidate.candidate_id for candidate in candidates] == ["placement-0001"]
    assert diagnostics == [
        {
            "generator": "placement",
            "variant": 1,
            "status": "duplicate",
            "reason": "placements match an earlier variant",
        },
        {
            "generator": "placement",
            "variant": 2,
            "status": "unavailable",
            "reason": "component C5 could not be placed",
        },
    ]


def test_generation_diagnostics_are_written_to_exploration_report(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    graph = _graph()
    source_fixture, source_graph = _source_fixture(tmp_path)
    placements = _placement_candidate(graph).changes["placements"]

    def fake_run(*args: object, **kwargs: object) -> object:
        command = args[0]
        assert isinstance(command, tuple)
        variant = int(command[command.index("--spacing-variant") + 1])
        if variant == 2:
            return type("Completed", (), {"returncode": 1, "stderr": "too tight"})()
        output = Path(str(command[command.index("--output") + 1]))
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(
                [
                    {
                        "refdes": refdes,
                        "x_mm": values["x_mm"],
                        "y_mm": values["y_mm"],
                        "rotation_deg": values["rotation_deg"],
                    }
                    for refdes, values in placements.items()
                ]
            ),
            encoding="utf-8",
        )
        return type("Completed", (), {"returncode": 0, "stderr": ""})()

    monkeypatch.setattr(exploration.subprocess, "run", fake_run)
    monkeypatch.setattr(exploration, "evaluate_design_predicates", _passing_pre_router)
    monkeypatch.setattr(
        exploration, "enumerate_gpio_assignment_candidates", lambda *_args: ()
    )
    result = explore_board_candidates(
        source_graph,
        source_fixture,
        tmp_path / "out",
        max_candidates=3,
        dry_run=True,
        pipeline_runner=lambda _fixture, _out: {},
    )

    assert result.report["candidate_generation"] == [
        {
            "generator": "placement",
            "variant": 1,
            "status": "duplicate",
            "reason": "placements match an earlier variant",
        },
        {
            "generator": "placement",
            "variant": 2,
            "status": "unavailable",
            "reason": "too tight",
        },
    ]


def test_variant_zero_failure_remains_fail_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    graph = _graph()

    def fake_run(*args: object, **kwargs: object) -> object:
        return type("Completed", (), {"returncode": 1, "stderr": "placement failed"})()

    monkeypatch.setattr(exploration.subprocess, "run", fake_run)
    with pytest.raises(ExplorationError, match="placement skill failed"):
        exploration._placement_candidates(
            GRAPH_PATH, FIXTURE_DIR, tmp_path, graph, max_variants=3
        )


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
        lambda *_args, **_kwargs: (_placement_candidate(graph),),
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
        lambda *_args, **_kwargs: (_placement_candidate(graph),),
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
        lambda *_args, **_kwargs: (_placement_candidate(graph),),
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
        lambda *_args, **_kwargs: (_placement_candidate(graph),),
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
        lambda *_args, **_kwargs: (_placement_candidate(graph),),
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


def test_runtime_observation_failure_stops_without_gate_rejection(
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
        lambda *_args, **_kwargs: (_placement_candidate(graph),),
    )
    monkeypatch.setattr(exploration, "evaluate_design_predicates", _passing_pre_router)

    def observation_failure(_fixture: Path, _out: Path) -> None:
        raise RuntimeObservationError("candidate timing is unavailable")

    result = explore_board_candidates(
        source_graph,
        source_fixture,
        tmp_path / "out",
        max_candidates=1,
        pipeline_runner=observation_failure,
    )

    outcome = result.report["candidates"][0]["outcome"]
    assert outcome["status"] == "stopped"
    assert outcome["observation_failure"] is True
    assert all(
        candidate["outcome"]["status"] != "gate_rejected"
        for candidate in result.report["candidates"]
    )


def _shifted_placement_candidate(
    graph: DesignGraph, candidate_id: str, offset_mm: float
) -> ExplorationCandidate:
    candidate = _placement_candidate(graph)
    placements = {
        refdes: {**values, "x_mm": values["x_mm"] + offset_mm}
        for refdes, values in candidate.changes["placements"].items()
    }
    return ExplorationCandidate(
        candidate_id=candidate_id,
        kind=candidate.kind,
        dimensions=candidate.dimensions,
        changes={"placements": placements},
        provenance=candidate.provenance,
    )


def _source_fixture(tmp_path: Path) -> tuple[Path, Path]:
    source_fixture = tmp_path / "fixture"
    shutil.copytree(FIXTURE_DIR, source_fixture)
    source_graph = source_fixture / "graph.json"
    source_graph.write_text(GRAPH_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    return source_fixture, source_graph


def test_candidate_evaluation_refreshes_rationale_before_gates(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    graph = _graph()
    source_fixture, source_graph = _source_fixture(tmp_path)
    monkeypatch.setattr(
        exploration,
        "_placement_candidates",
        lambda *_args, **_kwargs: (
            _shifted_placement_candidate(graph, "placement-0001", 0.5),
        ),
    )
    monkeypatch.setattr(exploration, "evaluate_design_predicates", _passing_pre_router)
    observed: list[str] = []

    def runner(working_fixture: Path, _out: Path) -> object:
        working_graph = DesignGraph.model_validate_json(
            (working_fixture / "graph.json").read_text(encoding="utf-8")
        )
        document = RationaleDocument.model_validate_json(
            (working_fixture / "rationale.json").read_text(encoding="utf-8")
        )
        observed.append(check_rationale_coverage(working_graph, document).status)
        return {}

    result = explore_board_candidates(
        source_graph,
        source_fixture,
        tmp_path / "out",
        max_candidates=1,
        pipeline_runner=runner,
    )

    assert observed == ["pass"]
    assert result.report["status"] == "candidate_found"


def test_candidate_specific_rejection_evaluates_remaining_budget(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    graph = _graph()
    source_fixture, source_graph = _source_fixture(tmp_path)
    monkeypatch.setattr(
        exploration,
        "_placement_candidates",
        lambda *_args, **_kwargs: (
            _shifted_placement_candidate(graph, "placement-0001", 0.5),
            _shifted_placement_candidate(graph, "placement-0002", 1.0),
        ),
    )
    monkeypatch.setattr(
        exploration, "enumerate_gpio_assignment_candidates", lambda *_args: ()
    )
    monkeypatch.setattr(exploration, "evaluate_design_predicates", _passing_pre_router)
    evaluated: list[Path] = []

    def reject_first(working_fixture: Path, _out: Path) -> object:
        evaluated.append(working_fixture)
        if len(evaluated) == 1:
            raise RuntimeError("router rejected candidate")
        return {}

    result = explore_board_candidates(
        source_graph,
        source_fixture,
        tmp_path / "out",
        max_candidates=3,
        pipeline_runner=reject_first,
    )

    assert result.report["status"] == "candidate_found"
    assert result.report["winner_candidate_id"] == "placement-0002"
    assert result.report["evaluated_candidates"] == 2
    assert result.report["consumed_budget"] == 2
    assert result.report["remaining_budget"] == 1


def test_exhausted_candidate_pool_reports_remaining_budget(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    graph = _graph()
    source_fixture, source_graph = _source_fixture(tmp_path)
    monkeypatch.setattr(
        exploration,
        "_placement_candidates",
        lambda *_args, **_kwargs: (
            _shifted_placement_candidate(graph, "placement-0001", 0.5),
            _shifted_placement_candidate(graph, "placement-0002", 1.0),
        ),
    )
    monkeypatch.setattr(
        exploration, "enumerate_gpio_assignment_candidates", lambda *_args: ()
    )
    monkeypatch.setattr(exploration, "evaluate_design_predicates", _passing_pre_router)

    def reject(_fixture: Path, _out: Path) -> None:
        raise RuntimeError("router rejected candidate")

    result = explore_board_candidates(
        source_graph,
        source_fixture,
        tmp_path / "out",
        max_candidates=3,
        pipeline_runner=reject,
    )

    assert result.report["status"] == "exhausted"
    assert result.report["termination_reason"] == "candidate_pool_exhausted"
    assert result.report["evaluated_candidates"] == 2
    assert result.report["remaining_budget"] == 1


def test_multi_candidate_pool_exhausts_declared_budget(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    graph = _graph()
    source_fixture, source_graph = _source_fixture(tmp_path)
    monkeypatch.setattr(
        exploration,
        "_placement_candidates",
        lambda *_args, **_kwargs: (
            _shifted_placement_candidate(graph, "placement-0001", 0.5),
            _shifted_placement_candidate(graph, "placement-0002", 1.0),
            _shifted_placement_candidate(graph, "placement-0003", 1.5),
        ),
    )
    monkeypatch.setattr(
        exploration, "enumerate_gpio_assignment_candidates", lambda *_args: ()
    )
    monkeypatch.setattr(exploration, "evaluate_design_predicates", _passing_pre_router)

    def reject(_fixture: Path, _out: Path) -> None:
        raise RuntimeError("router rejected candidate")

    result = explore_board_candidates(
        source_graph,
        source_fixture,
        tmp_path / "out",
        max_candidates=3,
        pipeline_runner=reject,
    )

    assert result.report["evaluated_candidates"] == 3
    assert result.report["consumed_budget"] == 3
    assert result.report["remaining_budget"] == 0
    assert result.report["termination_reason"] == "candidate_budget_exhausted"


def test_fail_closed_stop_abandons_remaining_budget(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    graph = _graph()
    source_fixture, source_graph = _source_fixture(tmp_path)
    monkeypatch.setattr(
        exploration,
        "_placement_candidates",
        lambda *_args, **_kwargs: (
            _shifted_placement_candidate(graph, "placement-0001", 0.5),
            _shifted_placement_candidate(graph, "placement-0002", 1.0),
        ),
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
        max_candidates=3,
        pipeline_runner=reject_with_bad_evidence,
    )

    assert result.report["status"] == "stopped"
    assert result.report["termination_reason"] == "fail_closed_stop"
    assert result.report["evaluated_candidates"] == 1
    assert result.report["remaining_budget"] == 2


def test_missing_rationale_document_fails_closed(tmp_path: Path) -> None:
    source_fixture, source_graph = _source_fixture(tmp_path)
    (source_fixture / "rationale.json").unlink()

    with pytest.raises(ExplorationError, match="rationale document is invalid"):
        explore_board_candidates(
            source_graph,
            source_fixture,
            tmp_path / "out",
            max_candidates=1,
            pipeline_runner=lambda _fixture, _out: {},
        )


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
