from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from acd.core.electrical.pdn import analyze_pdn, pdn_markdown
from acd.schema import DesignGraph, PdnAnalysisRequest

ROOT = Path(__file__).parents[2]
GRAPH_PATH = ROOT / "fixtures/golden-design-1/graph.json"
REQUEST_PATH = ROOT / "fixtures/pdn/gd1-power.json"
BOARD_PATH = ROOT / "examples/sensor-node-20260820/board/routed/gd1.kicad_pcb"


def _graph_payload() -> dict[str, Any]:
    return json.loads(GRAPH_PATH.read_text(encoding="utf-8"))


def _graph(payload: dict[str, Any] | None = None) -> DesignGraph:
    return DesignGraph.model_validate(payload or _graph_payload())


def _request(payload: dict[str, Any] | None = None) -> PdnAnalysisRequest:
    return PdnAnalysisRequest.model_validate(
        payload
        or json.loads(REQUEST_PATH.read_text(encoding="utf-8"))
    )


def test_gd1_routed_board_passes_all_requested_paths() -> None:
    result = analyze_pdn(_graph(), _request(), BOARD_PATH)
    assert result.status == "pass"
    assert [path.path_id for path in result.paths] == [
        "p1-vbus-j1-u2",
        "p2-3v3-u2-u1",
        "p3-3v3-u2-u3",
    ]
    assert all(path.status == "pass" for path in result.paths)


def test_tightened_ir_drop_limit_fails() -> None:
    payload = json.loads(REQUEST_PATH.read_text(encoding="utf-8"))
    payload["paths"][0]["max_ir_drop_mv"] = 1.0
    result = analyze_pdn(_graph(), _request(payload), BOARD_PATH)
    path = result.paths[0]
    assert result.status == "fail"
    assert path.status == "fail"
    assert "maximum IR drop exceeded" in path.findings


def test_missing_copper_thickness_is_unknown() -> None:
    payload = _graph_payload()
    board = next(node for node in payload["nodes"] if node["kind"] == "electrical.board")
    board["attrs"].pop("outer_copper_thickness_um", None)
    result = analyze_pdn(_graph(payload), _request(), BOARD_PATH)
    assert result.status == "unknown"
    assert all(path.status == "unknown" for path in result.paths)


def test_unknown_net_is_rejected() -> None:
    payload = json.loads(REQUEST_PATH.read_text(encoding="utf-8"))
    payload["paths"][0]["net"] = "NOT_A_NET"
    with pytest.raises(ValueError, match="unknown net"):
        analyze_pdn(_graph(), _request(payload), BOARD_PATH)


def test_revision_mismatch_is_rejected() -> None:
    payload = json.loads(REQUEST_PATH.read_text(encoding="utf-8"))
    payload["revision"] = "r2"
    with pytest.raises(ValueError, match="mismatch"):
        analyze_pdn(_graph(), _request(payload), BOARD_PATH)


def test_cut_vbus_connectors_report_open_path(tmp_path: Path) -> None:
    board = BOARD_PATH.read_text(encoding="utf-8")
    for endpoint in ("12.55 17.305", "17.45 17.305"):
        board, count = re.subn(
            rf"\n\t\(segment\n\t\t\(start [^)]+\)\n\t\t\(end {re.escape(endpoint)}\).*?\n\t\)",
            "",
            board,
            count=1,
            flags=re.DOTALL,
        )
        assert count == 1
    temporary = tmp_path / "cut.kicad_pcb"
    temporary.write_text(board, encoding="utf-8")
    result = analyze_pdn(_graph(), _request(), temporary)
    assert result.status == "fail"
    assert result.paths[0].status == "fail"
    assert "open path in copper" in result.paths[0].findings


def test_markdown_is_deterministic() -> None:
    result = analyze_pdn(_graph(), _request(), BOARD_PATH)
    assert pdn_markdown(result) == pdn_markdown(result)
