"""Tests for the quality-report generator (inspection/traceability docs)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import generate_quality_report

REPOSITORY = Path(__file__).resolve().parents[5]
GRAPH_PATH = REPOSITORY / "fixtures" / "golden-design-1" / "graph.json"
RATIONALE_PATH = REPOSITORY / "fixtures" / "golden-design-1" / "rationale.json"

GRAPH = json.loads(GRAPH_PATH.read_text(encoding="utf-8"))
REVISION = str(GRAPH["revision"])


def _envelope(**overrides: object) -> dict[str, object]:
    envelope: dict[str, object] = {
        "tool_name": "test-tool",
        "tool_version": "1.0.0",
        "format_version": "1.0.0",
        "config_hash": "sha256:" + "0" * 64,
        "input_hash": "sha256:" + "1" * 64,
        "output_hash": "sha256:" + "2" * 64,
        "execution_env": "linux-x86_64; container=sha256:" + "3" * 64,
        "execution_context": "container",
        "container_image_digest": "sha256:" + "3" * 64,
        "measurement_conditions": "test",
        "convergence_state": "not_applicable",
        "target_revision": REVISION,
        "started_at": "2026-09-01T00:00:00Z",
        "finished_at": "2026-09-01T00:01:00Z",
        "exit_code": 0,
        "source_revision": "0" * 40,
        "source_tree_state": "clean",
    }
    envelope.update(overrides)
    return envelope


def _evidence(
    lane: str,
    *,
    claims: list[dict[str, object]] | None = None,
    **overrides: object,
) -> dict[str, object]:
    evidence: dict[str, object] = {
        "schema_version": "0.1",
        "evidence_id": f"evidence.gd1.{lane}",
        "target_revision": REVISION,
        "status": "valid",
        "envelope": _envelope(),
        "claims": claims
        if claims is not None
        else [
            {
                "subject_node": "board.gd1",
                "property": f"{lane}_claim",
                "value": 0,
                "verified": True,
            }
        ],
        "created_at": "2026-09-01T00:02:00Z",
    }
    evidence.update(overrides)
    return evidence


def _coverage() -> dict[str, object]:
    return {
        "status": "pass",
        "graph_id": str(GRAPH["graph_id"]),
        "revision": REVISION,
        "graph_id_match": True,
        "revision_match": True,
        "missing": [],
        "stale": [],
        "unknown_provenance": [],
        "orphan": [],
        "untraceable": [],
        "conflicting": [],
        "unclassified": [],
        "templated": [],
        "generator_violations": [],
        "required_count": 10,
        "covered_count": 10,
        "record_count": 3,
    }


def _predicates() -> dict[str, object]:
    return {
        "target_revision": REVISION,
        "status": "pass",
        "observation": {
            "predicates": [
                {
                    "name": "i2c_pullup",
                    "evaluation_stage": "pre_router",
                    "status": "pass",
                    "detail": "topology matches",
                }
            ]
        },
    }


def _dfm() -> dict[str, object]:
    return {
        "status": "pass",
        "profile_id": "example-fab",
        "target_revision": REVISION,
        "findings": [{"rule_id": "annular_ring", "message": "ok"}],
        "unknowns": {"width": {"reason": "not measured"}},
        "checks_not_implemented": [
            {"rule_id": "via_hole_to_hole", "reason": "not implemented"}
        ],
    }


def _inputs(
    tmp_path: Path,
    *,
    evidence: dict[str, dict[str, object]] | None = None,
) -> dict[str, Path]:
    root = tmp_path / "in"
    root.mkdir()
    files: dict[str, Path] = {}
    lanes = evidence or {
        lane: _evidence(lane) for lane in ("electrical", "mechanical", "firmware")
    }
    for lane, doc in lanes.items():
        path = root / f"evidence-{lane}.json"
        path.write_text(
            json.dumps(doc, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        files[lane] = path
    for name in ("coverage-board", "coverage-enclosure"):
        subdir = root / name
        subdir.mkdir()
        path = subdir / "rationale-coverage.json"
        path.write_text(
            json.dumps(_coverage(), ensure_ascii=False) + "\n", encoding="utf-8"
        )
        files[name] = path
    for name, doc in (
        ("predicates", _predicates()),
        ("dfm", _dfm()),
    ):
        path = root / f"{name}.json"
        path.write_text(
            json.dumps(doc, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        files[name] = path
    return files


def _argv(files: dict[str, Path], out_dir: Path, tmp_path: Path) -> list[str]:
    argv = [
        "--graph",
        str(GRAPH_PATH),
        "--evidence",
        str(files["electrical"]),
        "--evidence",
        str(files["mechanical"]),
        "--evidence",
        str(files["firmware"]),
        "--rationale-coverage",
        str(files["coverage-board"]),
        "--rationale-coverage",
        str(files["coverage-enclosure"]),
        "--rationale",
        str(RATIONALE_PATH),
        "--design-predicates",
        str(files["predicates"]),
        "--dfm-report",
        str(files["dfm"]),
        "--out-dir",
        str(out_dir),
        "--base-dir",
        str(tmp_path),
    ]
    return argv


def test_happy_path_writes_three_documents(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    files = _inputs(tmp_path)
    out_dir = tmp_path / "out"
    assert generate_quality_report.main(_argv(files, out_dir, tmp_path)) == 0
    for name in (
        "inspection-report.md",
        "traceability-report.md",
        "quality-report.json",
    ):
        assert (out_dir / name).is_file()
        provenance = json.loads(
            (out_dir / f"{name}.provenance.json").read_text(encoding="utf-8")
        )
        assert provenance["pass_evidence"] is False
    report = json.loads(
        (out_dir / "quality-report.json").read_text(encoding="utf-8")
    )
    assert report["artifact_kind"] == "quality_report"
    assert report["record_class"] == "L3"
    assert report["pass_evidence"] is False
    assert [entry["lane"] for entry in report["evidence"]] == [
        "electrical",
        "mechanical",
        "firmware",
    ]
    requirement_ids = {
        node["id"] for node in GRAPH["nodes"] if node["kind"] == "requirement"
    }
    traced = {row["requirement"] for row in report["traceability"]}
    assert traced == requirement_ids
    node_kinds = {node["id"]: node["kind"] for node in GRAPH["nodes"]}
    with_nodes = [
        row for row in report["traceability"] if row["design_nodes"]
    ]
    assert with_nodes, "expected at least one traced requirement"
    for row in with_nodes:
        for entry in row["design_nodes"]:
            assert entry["kind"] == node_kinds[entry["id"]]
    req_004 = next(
        row for row in report["traceability"] if row["requirement"] == "req.gd1-req-004"
    )
    assert {entry["id"] for entry in req_004["design_nodes"]} == {
        "fb.safety-power-boundary"
    }
    for row in report["traceability"]:
        for claim in row["claims"]:
            assert claim["subject_node"] in node_kinds
    assert {entry["file"] for entry in report["rationale_coverage"]} == {
        "in/coverage-board/rationale-coverage.json",
        "in/coverage-enclosure/rationale-coverage.json",
    }
    markdown = (out_dir / "traceability-report.md").read_text(encoding="utf-8")
    assert "`fb.safety-power-boundary`" in markdown
    assert "| lane | 対象ノード | 属性 | 値 | verified |" in markdown
    assert "req.gd1-req-004" in markdown
    assert "via_hole_to_hole" in report["dfm"]["checks_not_implemented"][0][
        "rule_id"
    ]


def test_json_output_is_deterministic(tmp_path: Path) -> None:
    files = _inputs(tmp_path)
    out_a = tmp_path / "a"
    out_b = tmp_path / "b"
    assert generate_quality_report.main(_argv(files, out_a, tmp_path)) == 0
    assert generate_quality_report.main(_argv(files, out_b, tmp_path)) == 0
    assert (out_a / "quality-report.json").read_bytes() == (
        out_b / "quality-report.json"
    ).read_bytes()


def test_missing_required_lane_evidence_fails(tmp_path: Path) -> None:
    files = _inputs(tmp_path)
    argv = _argv(files, tmp_path / "out", tmp_path)
    index = argv.index(str(files["firmware"]))
    del argv[index - 1 : index + 1]
    with pytest.raises(
        generate_quality_report.DocumentGenerationError,
        match="firmware",
    ):
        generate_quality_report.main(argv)


def test_host_context_evidence_fails(tmp_path: Path) -> None:
    bad = _evidence(
        "electrical",
        envelope=_envelope(
            execution_context="host", container_image_digest=None
        ),
    )
    files = _inputs(
        tmp_path,
        evidence={
            "electrical": bad,
            "mechanical": _evidence("mechanical"),
            "firmware": _evidence("firmware"),
        },
    )
    with pytest.raises(
        generate_quality_report.DocumentGenerationError,
        match="authoritative Evidence",
    ):
        generate_quality_report.main(_argv(files, tmp_path / "out", tmp_path))


def test_invalid_evidence_status_fails(tmp_path: Path) -> None:
    files = _inputs(
        tmp_path,
        evidence={
            "electrical": _evidence("electrical", status="invalidated"),
            "mechanical": _evidence("mechanical"),
            "firmware": _evidence("firmware"),
        },
    )
    with pytest.raises(
        generate_quality_report.DocumentGenerationError, match="status"
    ):
        generate_quality_report.main(_argv(files, tmp_path / "out", tmp_path))


def test_evidence_revision_mismatch_fails(tmp_path: Path) -> None:
    bad = _evidence("electrical", target_revision="r999")
    bad["envelope"] = _envelope(target_revision="r999")
    files = _inputs(
        tmp_path,
        evidence={
            "electrical": bad,
            "mechanical": _evidence("mechanical"),
            "firmware": _evidence("firmware"),
        },
    )
    with pytest.raises(
        generate_quality_report.DocumentGenerationError, match="revision"
    ):
        generate_quality_report.main(_argv(files, tmp_path / "out", tmp_path))


def test_coverage_fail_status_fails(tmp_path: Path) -> None:
    files = _inputs(tmp_path)
    coverage = _coverage()
    coverage["status"] = "fail"
    files["coverage-board"].write_text(
        json.dumps(coverage, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    with pytest.raises(
        generate_quality_report.DocumentGenerationError, match="coverage"
    ):
        generate_quality_report.main(_argv(files, tmp_path / "out", tmp_path))


def test_coverage_revision_mismatch_fails(tmp_path: Path) -> None:
    files = _inputs(tmp_path)
    coverage = _coverage()
    coverage["revision"] = "r999"
    files["coverage-board"].write_text(
        json.dumps(coverage, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    with pytest.raises(
        generate_quality_report.DocumentGenerationError, match="revision"
    ):
        generate_quality_report.main(_argv(files, tmp_path / "out", tmp_path))


def test_rationale_revision_mismatch_fails(tmp_path: Path) -> None:
    files = _inputs(tmp_path)
    rationale = json.loads(RATIONALE_PATH.read_text(encoding="utf-8"))
    rationale["revision"] = "r999"
    bad = tmp_path / "in" / "rationale-bad.json"
    bad.write_text(
        json.dumps(rationale, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    argv = _argv(files, tmp_path / "out", tmp_path)
    argv[argv.index(str(RATIONALE_PATH))] = str(bad)
    with pytest.raises(
        generate_quality_report.DocumentGenerationError, match="rationale"
    ):
        generate_quality_report.main(argv)


def test_dfm_revision_mismatch_fails(tmp_path: Path) -> None:
    files = _inputs(tmp_path)
    dfm = _dfm()
    dfm["target_revision"] = "r999"
    files["dfm"].write_text(
        json.dumps(dfm, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    with pytest.raises(
        generate_quality_report.DocumentGenerationError, match="revision"
    ):
        generate_quality_report.main(_argv(files, tmp_path / "out", tmp_path))


def test_unknown_subject_node_fails(tmp_path: Path) -> None:
    bad = _evidence(
        "electrical",
        claims=[
            {
                "subject_node": "node.nonexistent",
                "property": "erc_error_count",
                "value": 0,
                "verified": True,
            }
        ],
    )
    files = _inputs(
        tmp_path,
        evidence={
            "electrical": bad,
            "mechanical": _evidence("mechanical"),
            "firmware": _evidence("firmware"),
        },
    )
    with pytest.raises(
        generate_quality_report.DocumentGenerationError, match="subject_node"
    ):
        generate_quality_report.main(_argv(files, tmp_path / "out", tmp_path))


def test_missing_dfm_file_fails(tmp_path: Path) -> None:
    files = _inputs(tmp_path)
    files["dfm"].unlink()
    with pytest.raises(
        generate_quality_report.DocumentGenerationError, match="DFM"
    ):
        generate_quality_report.main(_argv(files, tmp_path / "out", tmp_path))
