from __future__ import annotations

import json
from pathlib import Path

import pytest

from acd.core.firmware_consistency import check_firmware_graph_consistency
from acd.schema.design_graph import DesignGraph

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "golden-design-1" / "graph.json"


def _graph() -> DesignGraph:
    return DesignGraph.model_validate_json(FIXTURE.read_text(encoding="utf-8"))


def _report(graph: DesignGraph) -> dict[str, object]:
    module = next(node for node in graph.nodes if node.kind == "firmware.module")
    boot_log_message = module.attrs.get(
        "boot_log_message",
        f"ACD {graph.graph_id} fw boot target_revision=%s",
    )
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
            "boot_log_message": boot_log_message,
        },
    }


def test_matching_firmware_report_passes(tmp_path: Path) -> None:
    graph = _graph()
    report = tmp_path / "firmware-config-report.json"
    report.write_text(json.dumps(_report(graph)), encoding="utf-8")

    result = check_firmware_graph_consistency(graph, report)

    assert result.passed
    assert result.report_hash is not None


def test_unconfigured_boot_message_is_graph_derived(tmp_path: Path) -> None:
    graph = _graph().model_copy(
        update={
            "nodes": [
                node.model_copy(update={"attrs": dict(node.attrs)})
                if node.kind != "firmware.module"
                else node.model_copy(
                    update={
                        "attrs": {
                            key: value
                            for key, value in node.attrs.items()
                            if key != "boot_log_message"
                        }
                    }
                )
                for node in _graph().nodes
            ]
        }
    )
    report = tmp_path / "firmware-config-report.json"
    report.write_text(json.dumps(_report(graph)), encoding="utf-8")
    result = check_firmware_graph_consistency(graph, report)
    assert result.passed


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


@pytest.mark.parametrize(
    "boot_log_message",
    [
        "",
        "boot",
        'boot "quoted" %s',
        r"boot \\path %s",
        "boot\n%s",
        "boot %d %s",
        "boot %% %s",
        "boot %s%",
        "boot %s %s",
    ],
)
def test_malformed_boot_log_message_fails_closed(
    boot_log_message: str, tmp_path: Path
) -> None:
    graph = _graph()
    module = next(node for node in graph.nodes if node.kind == "firmware.module")
    broken = graph.model_copy(
        update={
            "nodes": [
                node.model_copy(
                    update={
                        "attrs": {
                            **node.attrs,
                            "boot_log_message": boot_log_message,
                        }
                    }
                )
                if node.id == module.id
                else node
                for node in graph.nodes
            ]
        }
    )
    report = tmp_path / "firmware-config-report.json"
    report.write_text(json.dumps(_report(broken)), encoding="utf-8")

    result = check_firmware_graph_consistency(broken, report)

    assert result.status == "unknown"
    assert result.reason is not None
    assert "C string literal template" in result.reason
