from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

from acd.core.bom_compliance import summarize_bom_compliance
from acd.core.electrical import extract_electrical_lane
from acd.schema import ComplianceDeclarationRegistry, DesignGraph

ROOT = Path(__file__).parents[2]
GRAPH_PATH = ROOT / "fixtures/golden-design-1/graph.json"
REGISTRY_PATH = ROOT / "fixtures/bom-compliance/gd1-2026-09.json"


def _graph() -> DesignGraph:
    return DesignGraph.model_validate_json(GRAPH_PATH.read_text(encoding="utf-8"))


def _payload() -> dict[str, Any]:
    return cast(
        dict[str, Any],
        json.loads(REGISTRY_PATH.read_text(encoding="utf-8")),
    )


def _summary(payload: dict[str, Any] | None = None):
    graph = _graph()
    registry = ComplianceDeclarationRegistry.model_validate(payload or _payload())
    return summarize_bom_compliance(
        graph,
        extract_electrical_lane(graph),
        registry,
    )


def _change_declaration(
    payload: dict[str, Any],
    mpn: str,
    regime: str,
    **updates: object,
) -> None:
    for entry in payload["entries"]:
        if entry["mpn"] == mpn:
            for declaration in entry["declarations"]:
                if declaration["regime"] == regime:
                    declaration.update(updates)
                    return
    raise AssertionError(f"declaration not found: {mpn}/{regime}")


def test_gd1_fixture_passes_and_keeps_no_mpn_separate() -> None:
    result = _summary()
    assert result.status == "pass"
    assert result.compliance_verdict is None
    assert result.authority == "declaration_summary"
    assert all(
        regime.counts.declared_compliant == 13
        for regime in result.per_regime
        if regime.regime in {"rohs", "reach_svhc"}
    )
    no_mpn = next(part for part in result.per_part if part.mpn == "no_mpn")
    assert no_mpn.refdes == [
        "H1",
        "H2",
        "H3",
        "H4",
        "TP1",
        "TP2",
        "TP3",
        "TP4",
        "TP5",
        "TP6",
        "TP7",
    ]


def test_not_declared_part_is_unknown_and_listed() -> None:
    payload = _payload()
    _change_declaration(
        payload,
        "SHT40-AD1B-R3",
        "rohs",
        declared_status="not_declared",
    )
    result = _summary(payload)
    assert result.status == "unknown"
    rohs = next(item for item in result.per_regime if item.regime == "rohs")
    assert rohs.unknown_parts == ["SHT40-AD1B-R3"]
    assert rohs.counts.not_declared == 1


def test_declared_non_compliant_part_fails() -> None:
    payload = _payload()
    _change_declaration(
        payload,
        "SHT40-AD1B-R3",
        "rohs",
        declared_status="declared_non_compliant",
    )
    result = _summary(payload)
    assert result.status == "fail"
    rohs = next(item for item in result.per_regime if item.regime == "rohs")
    assert rohs.non_compliant_parts == ["SHT40-AD1B-R3"]


def test_stale_declaration_is_unknown() -> None:
    payload = _payload()
    _change_declaration(
        payload,
        "SHT40-AD1B-R3",
        "rohs",
        source={
            "kind": "manual_declaration",
            "reference": "internal:old",
            "observed_at": "2020-01-01",
        },
    )
    result = _summary(payload)
    assert result.status == "unknown"
    rohs = next(item for item in result.per_regime if item.regime == "rohs")
    assert rohs.counts.stale == 1
    assert rohs.unknown_parts == ["SHT40-AD1B-R3"]


def test_exempt_without_reference_is_unknown() -> None:
    payload = _payload()
    _change_declaration(
        payload,
        "SHT40-AD1B-R3",
        "rohs",
        declared_status="exempt",
    )
    result = _summary(payload)
    assert result.status == "unknown"


def test_required_regime_missing_from_registry_scope_is_unknown() -> None:
    payload = _payload()
    payload["regimes"] = ["rohs"]
    payload["policy"]["required_regimes"] = ["rohs", "reach_svhc"]
    result = _summary(payload)
    assert result.status == "unknown"
    reach = next(item for item in result.per_regime if item.regime == "reach_svhc")
    assert reach.in_scope is False
    assert reach.unknown_parts == [
        "0603WAF1001T5E",
        "0603WAF1002T5E",
        "0603WAF4701T5E",
        "0603WAF5101T5E",
        "AMS1117-3.3",
        "CL10A105KB8NNNC",
        "CL10A106MQ8NNNC",
        "CL10B104KB8NNNC",
        "ESP32-C3-MINI-1-N4",
        "KT-0603R",
        "SHT40-AD1B-R3",
        "TS-1088-AR02016",
        "TYPE-C-31-M-12",
    ]


def test_cli_revision_mismatch_exits_two_without_output(tmp_path: Path) -> None:
    payload = _payload()
    payload["revision"] = "r2"
    registry_path = tmp_path / "registry.json"
    output_path = tmp_path / "result.json"
    registry_path.write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/check_bom_compliance.py"),
            "--graph",
            str(GRAPH_PATH),
            "--registry",
            str(registry_path),
            "--out",
            str(output_path),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 2
    assert not output_path.exists()


def test_cli_markdown_is_deterministic(tmp_path: Path) -> None:
    outputs = []
    for index in (1, 2):
        output = tmp_path / f"result-{index}.json"
        markdown = tmp_path / f"result-{index}.md"
        completed = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/check_bom_compliance.py"),
                "--graph",
                str(GRAPH_PATH),
                "--registry",
                str(REGISTRY_PATH),
                "--out",
                str(output),
                "--out-md",
                str(markdown),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert completed.returncode == 0
        outputs.append((output.read_bytes(), markdown.read_bytes()))
    assert outputs[0] == outputs[1]
