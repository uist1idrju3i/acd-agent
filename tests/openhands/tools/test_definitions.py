"""Tests for ACD OpenHands SDK ToolDefinitions."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

import pytest
from openhands.sdk.agent.parallel_executor import ResourceLockManager
from openhands.sdk.tool import ToolDefinition, list_registered_tools

import acd.openhands.tools.definitions as sdk_tools
from acd.openhands.tools.definitions import (
    AcdBootstrapWorkspace,
    AcdBootstrapWorkspaceAction,
    AcdBootstrapWorkspaceObservation,
    AcdObservation,
    AcdProbeTools,
    AcdProbeToolsAction,
    AcdProbeToolsObservation,
    AcdRegisterFunctionalBlock,
    AcdRegisterFunctionalBlockAction,
    AcdRunBoardPipeline,
    AcdRunBoardPipelineAction,
    AcdRunBoardPipelineObservation,
    AcdRunDesignLoop,
    AcdRunDesignLoopAction,
    AcdRunDesignLoopObservation,
    AcdRunEnclosurePipeline,
    AcdRunEnclosurePipelineAction,
    AcdValidateDesignGraph,
    AcdValidateDesignGraphAction,
    AcdValidateDesignGraphObservation,
    register_acd_tools,
)


def _execute(tool: Any, action: Any) -> AcdObservation:
    executor = tool.executor
    assert executor is not None
    return executor(action)


def test_bootstrap_workspace_propagates_record_and_provenance(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    report = {
        "ok": True,
        "failure_reason": None,
        "bootstrap_record_path": str(tmp_path / ".openhands/bootstrap-record.json"),
        "_returncode": 0,
    }

    def fake_bootstrap(
        repo_url: str,
        revision: str,
        workspace: Path,
    ) -> tuple[dict[str, Any], dict[str, str]]:
        del repo_url, revision, workspace
        return report, {
            "script": "init_workspace.py",
            "script_sha256": "sha256:" + "a" * 64,
        }

    monkeypatch.setattr(sdk_tools, "run_bootstrap", fake_bootstrap)
    tool = AcdBootstrapWorkspace.create()[0]
    result = _execute(
        tool,
        AcdBootstrapWorkspaceAction(
            repo_url="https://example.test/acd.git",
            revision="a" * 40,
            workspace=str(tmp_path / "workspace"),
        ),
    )
    assert isinstance(result, AcdBootstrapWorkspaceObservation)
    assert result.ok is True
    assert result.fail_closed is False
    assert result.bootstrap_record_path == report["bootstrap_record_path"]
    assert result.provenance is not None


def test_probe_tools_shape_and_unknown_is_fail_closed() -> None:
    tool = AcdProbeTools.create()[0]
    result = _execute(tool, AcdProbeToolsAction())
    assert result.ok is True
    assert result.operation == "probe_tools"
    assert isinstance(result.results, list)
    assert result.versions is not None
    assert set(result.versions) == {"kicad-cli", "freerouting", "cad-kernel"}
    if result.fail_closed:
        assert "not pass evidence" in result.to_llm_content[0].text.lower()


def test_probe_success_llm_content_lists_versions_and_unknowns() -> None:
    result = AcdProbeToolsObservation(
        ok=True,
        operation="probe_tools",
        results=[{"tool_name": "known", "is_known": True}],
        versions={"known": "1.2.3"},
        fail_closed=False,
    )
    text = result.to_llm_content[0].text
    assert "known=1.2.3" in text


def test_validate_success_llm_content_lists_graph_facts() -> None:
    result = AcdValidateDesignGraphObservation(
        ok=True,
        operation="validate_design_graph",
        graph_id="gd1",
        revision="r7",
        node_count=12,
        fail_closed=False,
    )
    text = result.to_llm_content[0].text
    assert "graph_id=gd1" in text
    assert "revision=r7" in text
    assert "node_count=12" in text


def test_pipeline_success_llm_content_lists_output_facts() -> None:
    result = AcdRunBoardPipelineObservation(
        ok=True,
        operation="run_board_pipeline",
        output_path="out/gd1",
        envelopes=[{"path": "out/gd1/e.json", "envelope": {}}],
        summary={"zeta": 1, "alpha": {"status": "passed"}},
        fail_closed=False,
    )
    text = result.to_llm_content[0].text
    assert "output_path=out/gd1" in text
    assert "envelopes=1" in text
    assert "summary_keys=alpha, zeta" in text


def test_design_loop_tool_preserves_fail_closed_observation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    expected: dict[str, Any] = {
        "ok": False,
        "fail_closed": True,
        "pass_evidence": False,
        "graph_id": "example",
        "failed_stage": "board-pipeline",
        "failure_reason": "intentional failure",
        "results": [],
    }

    def fake_run_design_loop(*args: Any, **kwargs: Any) -> dict[str, Any]:
        del args, kwargs
        return expected

    monkeypatch.setattr(
        "acd.pipeline.design_loop.run_design_loop",
        fake_run_design_loop,
    )
    tool = AcdRunDesignLoop.create()[0]
    result = _execute(
        tool,
        AcdRunDesignLoopAction(order_total=str(tmp_path / "order-total.json")),
    )

    assert isinstance(result, AcdRunDesignLoopObservation)
    assert result.ok is False
    assert result.fail_closed is True
    assert result.pass_evidence is False
    assert result.summary == expected


def test_design_loop_tool_declares_graph_policy_skill_and_output_resources(
    tmp_path: Path,
) -> None:
    action = AcdRunDesignLoopAction(
        fixture=str(tmp_path / "fixture"),
        order_total=str(tmp_path / "order-total.json"),
        policy=str(tmp_path / "policy.json"),
        repository=str(tmp_path),
        out_root=str(tmp_path / "out"),
    )
    resources = AcdRunDesignLoop.create()[0].declared_resources(action)

    assert resources.declared is True
    assert f"file:{(tmp_path / 'fixture' / 'graph.json').resolve()}" in resources.keys
    assert f"file:{(tmp_path / 'order-total.json').resolve()}" in resources.keys
    assert f"file:{(tmp_path / 'policy.json').resolve()}" in resources.keys
    assert any(key.startswith("file:") and "run_fw_pipeline.py" in key for key in resources.keys)
    assert f"acd-out:{(tmp_path / 'out').resolve()}" in resources.keys


def test_validate_design_graph_missing_path_is_fail_closed(tmp_path: Path) -> None:
    path = tmp_path / "missing.json"
    tool = AcdValidateDesignGraph.create()[0]
    result = _execute(tool, AcdValidateDesignGraphAction(path=str(path)))
    assert result.ok is False
    assert result.fail_closed is True
    assert result.failure_reason == f"design graph does not exist: {path}"
    assert result.failure_reason is not None
    assert result.failure_reason in result.to_llm_content[0].text
    assert "not pass evidence" in result.to_llm_content[0].text.lower()


def test_acd_tools_declare_shared_resources_and_probe_is_read_only(
    tmp_path: Path,
) -> None:
    graph = tmp_path / "fixture" / "graph.json"
    board_out = tmp_path / "board-out"
    enclosure_out = tmp_path / "enclosure-out"
    fixture = graph.parent
    board_action = AcdRunBoardPipelineAction(
        fixture=str(fixture),
        out=str(board_out),
    )
    enclosure_action = AcdRunEnclosurePipelineAction(
        fixture=str(fixture),
        out=str(enclosure_out),
    )

    probe_resources = AcdProbeTools.create()[0].declared_resources(
        AcdProbeToolsAction()
    )
    assert probe_resources.declared is True
    assert probe_resources.keys == ()

    validate_resources = AcdValidateDesignGraph.create()[0].declared_resources(
        AcdValidateDesignGraphAction(path=str(graph))
    )
    assert validate_resources.keys == (f"file:{graph.resolve()}",)

    board_resources = AcdRunBoardPipeline.create()[0].declared_resources(
        board_action
    )
    assert board_resources.keys == (
        f"file:{graph.resolve()}",
        f"acd-out:{board_out.resolve()}",
    )
    enclosure_resources = AcdRunEnclosurePipeline.create()[0].declared_resources(
        enclosure_action
    )
    assert enclosure_resources.keys == (
        f"file:{graph.resolve()}",
        f"acd-out:{enclosure_out.resolve()}",
    )


def test_register_functional_block_declares_registry_and_contract_resources(
    tmp_path: Path,
) -> None:
    contract = tmp_path / "contract.json"
    registry = tmp_path / "registry.json"
    contract.write_text("{}", encoding="utf-8")
    action = AcdRegisterFunctionalBlockAction(
        contract=str(contract),
        registry=str(registry),
    )
    resources = AcdRegisterFunctionalBlock.create()[0].declared_resources(action)
    assert resources.declared is True
    assert resources.keys == (
        f"file:{contract.resolve()}",
        f"file:{registry.resolve()}",
    )


def test_register_functional_block_tool_reports_hashes_and_dry_run(
    tmp_path: Path,
) -> None:
    source = Path(__file__).parents[3] / "contracts" / "functional-block-registry.json"
    registry = tmp_path / "registry.json"
    registry.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    action = AcdRegisterFunctionalBlockAction(
        contract=json.dumps(
            {
                "block_id": "tool_declared_block",
                "title": "Tool declared block",
                "description": "A declaration entered through the agent tool.",
                "required_predicates": ["i2c_pullup", "power_boundary"],
                "allowed_change_dimensions": [],
            }
        ),
        registry=str(registry),
        dry_run=True,
    )
    result = _execute(AcdRegisterFunctionalBlock.create()[0], action)
    assert result.ok is True
    assert result.fail_closed is False
    assert result.prior_registry_hash is not None
    assert result.new_registry_hash is not None
    assert result.prior_registry_hash != result.new_registry_hash
    assert result.written is False
    assert result.to_llm_content[0].text.find("not gate evidence") >= 0
    assert "tool_declared_block" not in registry.read_text(encoding="utf-8")


def test_acd_tool_resource_resolution_failure_serializes() -> None:
    action = AcdValidateDesignGraphAction(path="\x00")
    resources = AcdValidateDesignGraph.create()[0].declared_resources(action)
    assert resources.declared is False


def test_same_output_resource_is_serialized_by_parallel_executor(
    tmp_path: Path,
) -> None:
    fixture = tmp_path / "fixture"
    action = AcdRunBoardPipelineAction(
        fixture=str(fixture),
        out=str(tmp_path / "out"),
    )
    entered = threading.Event()
    release = threading.Event()
    active = 0
    max_active = 0
    active_lock = threading.Lock()

    board_tool: ToolDefinition[
        AcdRunBoardPipelineAction, AcdRunBoardPipelineObservation
    ] = AcdRunBoardPipeline.create()[0]
    resources = board_tool.declared_resources(action)
    assert resources.declared is True
    keys = list(resources.keys)
    lock_manager = ResourceLockManager()

    def runner() -> None:
        nonlocal active, max_active
        with lock_manager.lock(*keys):
            with active_lock:
                active += 1
                max_active = max(max_active, active)
            entered.set()
            assert release.wait(timeout=5)
            with active_lock:
                active -= 1

    workers = [threading.Thread(target=runner) for _ in range(2)]
    for worker in workers:
        worker.start()
    assert entered.wait(timeout=5)
    with active_lock:
        assert max_active == 1
    release.set()
    for worker in workers:
        worker.join(timeout=5)
        assert not worker.is_alive()
    assert max_active == 1


def test_validate_design_graph_valid_and_invalid(tmp_path: Path) -> None:
    valid = tmp_path / "valid.json"
    valid.write_text(
        json.dumps({"graph_id": "test", "revision": "r1", "nodes": []}),
        encoding="utf-8",
    )
    tool = AcdValidateDesignGraph.create()[0]
    result = _execute(tool, AcdValidateDesignGraphAction(path=str(valid)))
    assert result.ok is True
    assert result.node_count == 0

    invalid = tmp_path / "invalid.json"
    invalid.write_text("[]", encoding="utf-8")
    result = _execute(tool, AcdValidateDesignGraphAction(path=str(invalid)))
    assert result.ok is False
    assert result.fail_closed is True


def test_pipeline_tools_validate_inputs_fail_closed(tmp_path: Path) -> None:
    board = _execute(
        AcdRunBoardPipeline.create()[0],
        AcdRunBoardPipelineAction(fixture=str(tmp_path / "missing")),
    )
    assert board.ok is False
    assert board.fail_closed is True

    enclosure = _execute(
        AcdRunEnclosurePipeline.create()[0],
        AcdRunEnclosurePipelineAction(fixture=str(tmp_path / "missing")),
    )
    assert enclosure.ok is False
    assert enclosure.fail_closed is True

    fixture = tmp_path / "fixture"
    (fixture / "graph.json").parent.mkdir(parents=True)
    (fixture / "graph.json").write_text("{}", encoding="utf-8")
    board = _execute(
        AcdRunBoardPipeline.create()[0],
        AcdRunBoardPipelineAction(fixture=str(fixture), max_passes=0),
    )
    assert board.ok is False
    assert board.fail_closed is True
    board = _execute(
        AcdRunBoardPipeline.create()[0],
        AcdRunBoardPipelineAction(
            fixture=str(fixture),
            fab_profile=str(tmp_path / "missing-profile.json"),
        ),
    )
    assert board.ok is False
    assert board.fail_closed is True


def test_pipeline_exception_keeps_output_and_envelopes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    out = tmp_path / "out"
    out.mkdir()
    (out / "envelope.json").write_text(
        json.dumps(
            {
                "tool_name": "test",
                "tool_version": "1",
                "input_hash": "in",
                "output_hash": "out",
            }
        ),
        encoding="utf-8",
    )
    fixture = Path("fixtures/golden-design-1")
    monkeypatch.setattr(sdk_tools, "run_enclosure", _raise_pipeline)
    result = _execute(
        AcdRunEnclosurePipeline.create()[0],
        AcdRunEnclosurePipelineAction(fixture=str(fixture), out=str(out)),
    )
    assert result.ok is False
    assert result.fail_closed is True
    assert result.output_path == str(out)
    assert result.envelopes is not None
    assert result.envelopes[0]["path"] == str(out / "envelope.json")


def _raise_pipeline(*args: object, **kwargs: object) -> dict[str, object]:
    del args, kwargs
    raise RuntimeError("pipeline exploded")


def test_registration_is_idempotent_and_tool_schemas_are_exposed() -> None:
    register_acd_tools()
    register_acd_tools()
    assert {
        "acd_probe_tools",
        "acd_validate_design_graph",
        "acd_register_functional_block",
        "acd_run_board_pipeline",
        "acd_run_enclosure_pipeline",
    }.issubset(set(list_registered_tools()))
    tool = AcdRunBoardPipeline.create()[0]
    schema = tool.action_type.model_json_schema()
    assert "max_passes" in schema["properties"]
    assert "description" in schema["properties"]["max_passes"]
    assert tool.annotations is not None
    assert tool.annotations.idempotentHint is True


def test_removed_server_is_not_a_runtime_or_dependency_reference() -> None:
    root = Path(__file__).parents[3]
    ignored = {".venv", "vendor", ".git", "out", "__pycache__"}
    references: list[str] = []
    for path in root.rglob("*"):
        if not path.is_file() or any(part in ignored for part in path.parts):
            continue
        if path.suffix not in {".py", ".toml", ".json", ".lock"}:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore").lower()
        if (
            "fast" + "mcp" in text
            or "acd-" + "mcp" in text
            or "." + "mcp.json" in text
        ) and path.name != "uv.lock":
            references.append(str(path.relative_to(root)))
    assert references == []
