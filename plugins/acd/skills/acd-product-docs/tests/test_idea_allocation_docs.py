"""Tests for the idea-allocation document generator."""

from __future__ import annotations

import json
from pathlib import Path

import generate_idea_allocation_docs

REPOSITORY = Path(__file__).resolve().parents[5]
RESP_FIXTURE = REPOSITORY / "fixtures" / "responsibility" / "sample"


def _idea() -> dict[str, object]:
    return {
        "schema_version": "0.1",
        "idea_id": "idea.resp-sample",
        "revision": "r1",
        "title": "USB thermometer",
        "purpose": {"status": "open"},
        "success_criteria": [],
        "functions": [
            {
                "function_id": "fn-measure-temp",
                "function_class": "temperature_sensor",
                "priority": "must",
                "description": {"status": "open"},
            },
            {
                "function_id": "fn-stream-usb",
                "function_class": "usb_mcu",
                "priority": "must",
                "description": {"status": "open"},
            },
        ],
    }


def _write_inputs(tmp_path: Path) -> dict[str, Path]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    graph = (RESP_FIXTURE / "graph.json").read_text(encoding="utf-8")
    responsibility = (RESP_FIXTURE / "responsibility.json").read_text(
        encoding="utf-8"
    )
    catalog = (
        REPOSITORY
        / "fixtures"
        / "idea"
        / "sample-usb-thermometer"
        / "estimate-catalog.json"
    ).read_text(encoding="utf-8")
    paths = {
        "graph": tmp_path / "graph.json",
        "idea": tmp_path / "idea.json",
        "catalog": tmp_path / "estimate-catalog.json",
        "responsibility": tmp_path / "responsibility.json",
    }
    paths["graph"].write_text(graph, encoding="utf-8")
    paths["idea"].write_text(
        json.dumps(_idea(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    paths["catalog"].write_text(catalog, encoding="utf-8")
    paths["responsibility"].write_text(responsibility, encoding="utf-8")
    return paths


def _run(paths: dict[str, Path], out_dir: Path) -> int:
    return generate_idea_allocation_docs.main(
        [
            "--graph", str(paths["graph"]),
            "--idea", str(paths["idea"]),
            "--estimate-catalog", str(paths["catalog"]),
            "--responsibility", str(paths["responsibility"]),
            "--out-dir", str(out_dir),
            "--base-dir", str(out_dir.parent),
        ]
    )


EXPECTED = [
    "idea-record.md",
    "rough-estimate.md",
    "rough-estimate.json",
    "responsibility-allocation.md",
    "responsibility-allocation.json",
    "cross-domain-block-diagram.svg",
]


def test_happy_path_writes_six_documents_with_provenance(
    tmp_path: Path,
) -> None:
    paths = _write_inputs(tmp_path)
    out_dir = tmp_path / "docs"
    assert _run(paths, out_dir) == 0
    for name in EXPECTED:
        assert (out_dir / name).is_file()
        provenance = json.loads(
            (out_dir / f"{name}.provenance.json").read_text(encoding="utf-8")
        )
        assert provenance["pass_evidence"] is False
        assert provenance["artifact_kind"] == "generated_document"
    result = json.loads(
        (out_dir / "responsibility-allocation.json").read_text(
            encoding="utf-8"
        )
    )
    assert result["status"] == "pass"
    estimate = json.loads(
        (out_dir / "rough-estimate.json").read_text(encoding="utf-8")
    )
    assert estimate["record_class"] == "L3"


def test_deterministic_bytes(tmp_path: Path) -> None:
    paths = _write_inputs(tmp_path / "a")
    first = tmp_path / "out1"
    assert _run(paths, first) == 0
    paths2 = _write_inputs(tmp_path / "b")
    second = tmp_path / "out2"
    assert _run(paths2, second) == 0
    for name in EXPECTED:
        assert (first / name).read_bytes() == (second / name).read_bytes()


def test_gate_fail_still_renders(tmp_path: Path) -> None:
    paths = _write_inputs(tmp_path)
    declaration = json.loads(
        paths["responsibility"].read_text(encoding="utf-8")
    )
    declaration["functions"] = declaration["functions"][:1]
    paths["responsibility"].write_text(
        json.dumps(declaration, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    out_dir = tmp_path / "docs"
    assert _run(paths, out_dir) == 0
    body = (out_dir / "responsibility-allocation.md").read_text(
        encoding="utf-8"
    )
    assert "**fail**" in body
    result = json.loads(
        (out_dir / "responsibility-allocation.json").read_text(
            encoding="utf-8"
        )
    )
    assert result["status"] == "fail"


def test_graph_mismatch_fails_closed(tmp_path: Path) -> None:
    paths = _write_inputs(tmp_path)
    declaration = json.loads(
        paths["responsibility"].read_text(encoding="utf-8")
    )
    declaration["revision"] = "r9"
    paths["responsibility"].write_text(
        json.dumps(declaration, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    assert _run(paths, tmp_path / "docs") == 1


def test_function_not_in_idea_fails_closed(tmp_path: Path) -> None:
    paths = _write_inputs(tmp_path)
    declaration = json.loads(
        paths["responsibility"].read_text(encoding="utf-8")
    )
    declaration["functions"].append(
        {"function_id": "fn-ghost", "communication": ["usb"]}
    )
    paths["responsibility"].write_text(
        json.dumps(declaration, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    assert _run(paths, tmp_path / "docs") == 1


def test_dialogue_history_never_appears(tmp_path: Path) -> None:
    paths = _write_inputs(tmp_path)
    marker = "evt-0001-secret-user-statement"
    (tmp_path / "idea-dialogue.json").write_text(
        json.dumps({"turns": [{"marker": marker}]}), encoding="utf-8"
    )
    out_dir = tmp_path / "docs"
    assert _run(paths, out_dir) == 0
    for name in EXPECTED:
        assert marker not in (out_dir / name).read_text(encoding="utf-8")


def test_svg_boxes_and_dashed_one_sided(tmp_path: Path) -> None:
    paths = _write_inputs(tmp_path)
    declaration = json.loads(
        paths["responsibility"].read_text(encoding="utf-8")
    )
    declaration["interfaces"][0]["declared_by"] = ["firmware"]
    paths["responsibility"].write_text(
        json.dumps(declaration, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    out_dir = tmp_path / "docs"
    assert _run(paths, out_dir) == 0
    svg = (out_dir / "cross-domain-block-diagram.svg").read_text(
        encoding="utf-8"
    )
    assert svg.count("<rect") == 2  # firmware + pc_software
    assert ">firmware<" in svg and ">pc_software<" in svg
    assert 'stroke-dasharray="6 4"' in svg
    assert "temperature reading/usb serial" in svg
