"""Tests for ACD OpenHands SDK ToolDefinitions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from openhands.sdk.tool import list_registered_tools

import acd_tools.sdk_tools as sdk_tools
from acd_tools.sdk_tools import (
    AcdObservation,
    AcdProbeTools,
    AcdProbeToolsAction,
    AcdRunBoardPipeline,
    AcdRunBoardPipelineAction,
    AcdRunEnclosurePipeline,
    AcdRunEnclosurePipelineAction,
    AcdValidateDesignGraph,
    AcdValidateDesignGraphAction,
    register_acd_tools,
)


def _execute(tool: Any, action: Any) -> AcdObservation:
    executor = tool.executor
    assert executor is not None
    return executor(action)


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
