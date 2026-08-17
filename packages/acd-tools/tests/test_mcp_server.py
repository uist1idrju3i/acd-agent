"""Tests for the direct ACD MCP tool functions."""

from __future__ import annotations

import json
from pathlib import Path

from acd_tools.mcp_server import (
    probe_tools,
    run_board_pipeline,
    run_enclosure_pipeline,
    validate_design_graph,
)


def test_probe_tools_shape() -> None:
    result = probe_tools()
    assert result["ok"] is True
    assert result["operation"] == "probe_tools"
    assert isinstance(result["results"], list)
    assert set(result["versions"]) == {"kicad-cli", "freerouting", "cad-kernel"}


def test_validate_design_graph_missing_path(tmp_path: Path) -> None:
    result = validate_design_graph(str(tmp_path / "missing.json"))
    assert result == {
        "ok": False,
        "operation": "validate_design_graph",
        "failure_reason": f"design graph does not exist: {tmp_path / 'missing.json'}",
        "fail_closed": True,
    }


def test_validate_design_graph_valid_and_invalid(tmp_path: Path) -> None:
    valid = tmp_path / "valid.json"
    valid.write_text(
        json.dumps(
            {
                "graph_id": "test",
                "revision": "r1",
                "nodes": [],
            }
        ),
        encoding="utf-8",
    )
    result = validate_design_graph(str(valid))
    assert result["ok"] is True
    assert result["node_count"] == 0

    invalid = tmp_path / "invalid.json"
    invalid.write_text("[]", encoding="utf-8")
    result = validate_design_graph(str(invalid))
    assert result["ok"] is False
    assert result["fail_closed"] is True


def test_pipeline_tools_fail_closed_for_missing_fixture(tmp_path: Path) -> None:
    board = run_board_pipeline(fixture=str(tmp_path / "missing"))
    enclosure = run_enclosure_pipeline(fixture=str(tmp_path / "missing"))
    assert board["ok"] is False
    assert board["fail_closed"] is True
    assert enclosure["ok"] is False
    assert enclosure["fail_closed"] is True
