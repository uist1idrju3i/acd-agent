"""Tests for deterministic mechanical preflight diagnostics."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from acd.core.electrical import GraphExtractionError
from acd.core.mechanical import REQUIRED_MECHANICAL_ATTRS, extract_mechanical_lane
from acd.core.mechanical_preflight import check_mechanical_preflight
from acd.schema.design_graph import DesignGraph

ROOT = Path(__file__).resolve().parents[2]
GRAPH_PATH = ROOT / "fixtures" / "golden-design-1" / "graph.json"


def _graph() -> DesignGraph:
    return DesignGraph.model_validate_json(GRAPH_PATH.read_text(encoding="utf-8"))


def test_gd1_mechanical_preflight_passes() -> None:
    report = check_mechanical_preflight(_graph(), GRAPH_PATH.parent)
    assert report.status == "pass"
    assert report.findings == []


def test_mechanical_preflight_reports_all_missing_requirements(
    tmp_path: Path,
) -> None:
    graph = _graph()
    nodes = [
        node
        for node in graph.nodes
        if node.kind != "mechanical.enclosure"
        and node.id != "mechanical.component_body.30"
    ]
    nodes = [
        node.model_copy(
            update={
                "attrs": {
                    key: value
                    for key, value in node.attrs.items()
                    if key != "mount_hole_count"
                }
            }
        )
        if node.kind == "mechanical.outline"
        else node
        for node in nodes
    ]
    broken_graph = graph.model_copy(update={"nodes": nodes})
    fixture_dir = tmp_path / "fixture"
    fixture_dir.mkdir()
    report = check_mechanical_preflight(broken_graph, fixture_dir)

    assert report.status == "fail"
    assert {
        (finding.code, finding.node_kind, finding.attribute)
        for finding in report.findings
    } >= {
        ("rationale.coverage.missing", "", ""),
        ("mechanical.node.missing", "mechanical.enclosure", ""),
        ("mechanical.node.missing", "mechanical.component_body", ""),
        ("mechanical.attribute.missing", "mechanical.outline", "mount_hole_count"),
    }
    assert report.findings == sorted(
        report.findings,
        key=lambda finding: (
            finding.code,
            finding.node_kind,
            finding.node_id,
            finding.attribute,
            finding.detail,
        ),
    )


def test_mechanical_attribute_declarations_match_extractor() -> None:
    graph = _graph()
    for kind, attributes in REQUIRED_MECHANICAL_ATTRS.items():
        source = next(node for node in graph.nodes if node.kind == kind)
        for attribute in attributes:
            nodes = [
                node.model_copy(
                    update={
                        "attrs": {
                            key: value
                            for key, value in node.attrs.items()
                            if not (node.id == source.id and key == attribute)
                        }
                    }
                )
                for node in graph.nodes
            ]
            try:
                extract_mechanical_lane(graph.model_copy(update={"nodes": nodes}))
            except GraphExtractionError:
                continue
            raise AssertionError(f"{kind}.{attribute} was not required by extractor")


def test_enclosure_cli_writes_mechanical_preflight_report(
    tmp_path: Path,
) -> None:
    fixture_dir = tmp_path / "fixture"
    fixture_dir.mkdir()
    graph = _graph()
    graph_without_enclosure = graph.model_copy(
        update={
            "nodes": [
                node for node in graph.nodes if node.kind != "mechanical.enclosure"
            ]
        }
    )
    (fixture_dir / "graph.json").write_text(
        graph_without_enclosure.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    out_dir = tmp_path / "out"
    result = subprocess.run(
        [
            sys.executable,
            "scripts/run_enclosure_pipeline.py",
            "--fixture",
            str(fixture_dir),
            "--out",
            str(out_dir),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    report = json.loads(
        (out_dir / "preflight-mechanical.json").read_text(encoding="utf-8")
    )
    assert report["status"] == "fail"
    assert any(
        finding["code"] == "mechanical.node.missing"
        and finding["node_kind"] == "mechanical.enclosure"
        for finding in report["findings"]
    )
