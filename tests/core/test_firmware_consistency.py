from __future__ import annotations

import json
from pathlib import Path

from acd.core.firmware_consistency import check_firmware_graph_consistency
from acd.schema.design_graph import DesignGraph

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "golden-design-1" / "graph.json"


def _graph() -> DesignGraph:
    return DesignGraph.model_validate_json(FIXTURE.read_text(encoding="utf-8"))


def _report(graph: DesignGraph) -> dict[str, object]:
    pins = sorted(
        (
            {"node_id": node.id, "gpio": node.attrs["gpio"], "net": node.attrs["net"]}
            for node in graph.nodes
            if node.kind == "firmware.pin_assignment"
        ),
        key=lambda item: str(item["node_id"]),
    )
    return {
        "schema_version": 1,
        "graph_id": graph.graph_id,
        "target_revision": graph.revision,
        "pins": pins,
        "settings": {
            "led_blink_period_ms": 1000,
            "log_period_ms": 2000,
            "boot_log_message": "ACD GD1 fw boot target_revision=%s",
        },
    }


def test_matching_firmware_report_passes(tmp_path: Path) -> None:
    graph = _graph()
    report = tmp_path / "firmware-config-report.json"
    report.write_text(json.dumps(_report(graph)), encoding="utf-8")

    result = check_firmware_graph_consistency(graph, report)

    assert result.passed
    assert result.report_hash is not None


def test_firmware_report_mismatch_fails_closed(tmp_path: Path) -> None:
    graph = _graph()
    value = _report(graph)
    value["pins"][0]["gpio"] = 99  # type: ignore[index]
    report = tmp_path / "firmware-config-report.json"
    report.write_text(json.dumps(value), encoding="utf-8")

    result = check_firmware_graph_consistency(graph, report)

    assert not result.passed
    assert result.status == "unknown"


def test_missing_or_malformed_firmware_report_fails_closed(tmp_path: Path) -> None:
    graph = _graph()
    missing = check_firmware_graph_consistency(
        graph, tmp_path / "missing-firmware-config-report.json"
    )
    malformed_path = tmp_path / "malformed.json"
    malformed_path.write_text("{", encoding="utf-8")
    malformed = check_firmware_graph_consistency(graph, malformed_path)

    assert missing.status == "unknown"
    assert malformed.status == "unknown"
