"""FastMCP server exposing the existing deterministic ACD entrypoints."""

# pyright: reportMissingTypeStubs=false

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from fastmcp import FastMCP

from acd_core.rationale import check_rationale_coverage
from acd_pipeline.gd1_board import (
    run_pipeline as run_board,  # pyright: ignore[reportMissingTypeStubs]
)
from acd_pipeline.gd1_enclosure import (
    run_pipeline as run_enclosure,  # pyright: ignore[reportMissingTypeStubs]
)
from acd_schema.design_graph import DesignGraph
from acd_schema.rationale import RationaleDocument
from acd_tools.probe import probe_all

mcp = FastMCP("acd")


def _error(message: str, *, operation: str) -> dict[str, Any]:
    return {
        "ok": False,
        "operation": operation,
        "failure_reason": message,
        "fail_closed": True,
    }


def _envelopes(out_dir: Path) -> list[dict[str, Any]]:
    envelopes: list[dict[str, Any]] = []
    for path in sorted(out_dir.rglob("*.json")):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(value, dict) and {
            "tool_name",
            "tool_version",
            "input_hash",
            "output_hash",
        }.issubset(cast(dict[str, Any], value)):
            envelopes.append({"path": str(path), "envelope": value})
    return envelopes


@mcp.tool
def probe_tools() -> dict[str, Any]:
    """Probe configured external tools and return their versions."""
    try:
        report = probe_all()
        return {
            "ok": True,
            "operation": "probe_tools",
            "results": [result.model_dump(mode="json") for result in report.results],
            "versions": report.versions(),
            "fail_closed": any(not result.is_known for result in report.results),
        }
    except Exception as exc:
        return _error(str(exc), operation="probe_tools")


@mcp.tool
def validate_design_graph(path: str) -> dict[str, Any]:
    """Validate a canonical DesignGraph JSON file without projecting it."""
    try:
        graph_path = Path(path)
        if not graph_path.is_file():
            return _error(f"design graph does not exist: {path}", operation="validate_design_graph")
        graph = DesignGraph.model_validate(
            json.loads(graph_path.read_text(encoding="utf-8"))
        )
        return {
            "ok": True,
            "operation": "validate_design_graph",
            "graph_id": graph.graph_id,
            "revision": graph.revision,
            "node_count": len(graph.nodes),
            "path": str(graph_path),
            "fail_closed": False,
        }
    except (OSError, json.JSONDecodeError, ValueError, TypeError) as exc:
        return _error(str(exc), operation="validate_design_graph")


@mcp.tool
def validate_rationale(graph_path: str, rationale_path: str) -> dict[str, Any]:
    """Validate a rationale document against a canonical design graph."""
    operation = "validate_rationale"
    try:
        graph_file = Path(graph_path)
        rationale_file = Path(rationale_path)
        if not graph_file.is_file():
            return _error(f"design graph does not exist: {graph_path}", operation=operation)
        if not rationale_file.is_file():
            return _error(f"rationale does not exist: {rationale_path}", operation=operation)
        graph = DesignGraph.model_validate(json.loads(graph_file.read_text(encoding="utf-8")))
        document = RationaleDocument.model_validate(
            json.loads(rationale_file.read_text(encoding="utf-8"))
        )
        report = check_rationale_coverage(graph, document)
        return {
            "ok": report.status == "pass",
            "operation": operation,
            "failure_reason": None if report.status == "pass" else "rationale coverage failed",
            "fail_closed": report.status != "pass",
            "summary": report.model_dump(mode="json"),
        }
    except Exception as exc:
        return _error(str(exc), operation=operation)


@mcp.tool
def run_board_pipeline(
    fixture: str = "fixtures/golden-design-1",
    out: str = "out/gd1-mcp",
    fab_profile: str = "profiles/jlcpcb/fab-profile-jlcpcb-fr4-2l-1oz.json",
    max_passes: int = 3,
) -> dict[str, Any]:
    """Run the existing deterministic GD1 board pipeline."""
    try:
        fixture_path = Path(fixture)
        out_path = Path(out)
        profile_path = Path(fab_profile)
        if not (fixture_path / "graph.json").is_file():
            return _error(
                f"fixture graph does not exist: {fixture}",
                operation="run_board_pipeline",
            )
        if not profile_path.is_file():
            return _error(
                f"fab profile does not exist: {fab_profile}",
                operation="run_board_pipeline",
            )
        if max_passes <= 0:
            return _error("max_passes must be positive", operation="run_board_pipeline")
        summary = run_board(fixture_path, out_path, max_passes, profile_path)
        return {
            "ok": True,
            "operation": "run_board_pipeline",
            "summary": summary,
            "output_path": str(out_path),
            "envelopes": _envelopes(out_path),
            "fail_closed": False,
        }
    except Exception as exc:
        return {
            **_error(str(exc), operation="run_board_pipeline"),
            "output_path": str(out),
            "envelopes": _envelopes(Path(out)),
        }


@mcp.tool
def run_enclosure_pipeline(
    fixture: str = "fixtures/golden-design-1",
    out: str = "out/gd1-enclosure-mcp",
) -> dict[str, Any]:
    """Run the existing deterministic GD1 enclosure pipeline."""
    try:
        fixture_path = Path(fixture)
        out_path = Path(out)
        if not (fixture_path / "graph.json").is_file():
            return _error(
                f"fixture graph does not exist: {fixture}",
                operation="run_enclosure_pipeline",
            )
        summary = run_enclosure(fixture_path, out_path)
        return {
            "ok": True,
            "operation": "run_enclosure_pipeline",
            "summary": summary,
            "output_path": str(out_path),
            "envelopes": _envelopes(out_path),
            "fail_closed": False,
        }
    except Exception as exc:
        return {
            **_error(str(exc), operation="run_enclosure_pipeline"),
            "output_path": str(out),
            "envelopes": _envelopes(Path(out)),
        }


def main() -> None:
    """Start the ACD MCP server over stdio."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
