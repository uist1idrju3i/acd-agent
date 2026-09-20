"""Tests for deterministic review-package generation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import generate_review_package
from acd.core.graph_diff import build_graph_diff
from acd.schema.design_graph import DesignGraph
from acd.schema.visual_projection import VisualProjectionSet

REPOSITORY = Path(__file__).resolve().parents[5]
GRAPH_PATH = REPOSITORY / "fixtures" / "golden-design-1" / "graph.json"
ANALYSIS_PATH = REPOSITORY / "fixtures" / "golden-design-1" / "analysis"


def _inputs(tmp_path: Path) -> dict[str, Path]:
    graph = json.loads(GRAPH_PATH.read_text(encoding="utf-8"))
    current = json.loads(json.dumps(graph))
    current["revision"] = "r2"
    removed = current["nodes"].pop(0)
    current["nodes"][0]["attrs"]["text"] += " changed"
    current["nodes"][0]["depends_on"] = ["req.gd1-req-006"]
    added = json.loads(json.dumps(removed))
    added["id"] = "req.gd1-req-added"
    current["nodes"].append(added)
    current_path = tmp_path / "graph-current.json"
    current_path.write_text(json.dumps(current, ensure_ascii=False) + "\n", encoding="utf-8")
    previous = json.loads(json.dumps(graph))
    previous["revision"] = "r1"
    next(node for node in previous["nodes"] if node["id"] == "req.gd1-req-004")["depends_on"] = [
        "req.gd1-req-005"
    ]
    previous_path = tmp_path / "graph-previous.json"
    previous_path.write_text(json.dumps(previous, ensure_ascii=False) + "\n", encoding="utf-8")
    predicates = tmp_path / "design-predicates.json"
    predicates.write_text(
        json.dumps(
            {
                "target_revision": "r2",
                "status": "pass",
                "observation": {
                    "predicates": [
                        {
                            "name": "predicate.example",
                            "evaluation_stage": "test",
                            "status": "pass",
                            "detail": "traceable observation",
                        }
                    ]
                },
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    dfm = tmp_path / "dfm-report.json"
    dfm.write_text(
        json.dumps(
            {
                "target_revision": "r2",
                "status": "pass",
                "profile_id": "test-profile",
                "findings": [{"rule_id": "dfm-1", "message": "review finding"}],
                "unknowns": {"width": {"reason": "not measured"}},
                "checks_not_implemented": [{"rule_id": "dfm-2", "reason": "not implemented"}],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    image = tmp_path / "projection.svg"
    image.write_text("<svg></svg>\n", encoding="utf-8")
    projection = {
        "projection_id": "test-projection",
        "projection_type": "schematic_view",
        "domain": "electrical",
        "source_revision": "r2",
        "input_files": [{"path": "graph.json", "content_hash": "sha256:" + "1" * 64}],
        "renderer": {
            "renderer_type": "acd-svg",
            "tool_name": "acd-svg",
            "tool_version": "1.0.0",
        },
        "media_type": "image/svg+xml",
        "resolution": {
            "width": "1px",
            "height": "1px",
            "view_box": [0.0, 0.0, 1.0, 1.0],
        },
        "normalization_rule_id": "test-normalization-v1",
        "normalization_rule_description": "test",
        "image_hash": "sha256:" + "2" * 64,
        "generated_at": "2026-01-01T00:00:00Z",
        "regeneration_check": {
            "status": "reproduced",
            "first_image_hash": "sha256:" + "2" * 64,
            "second_image_hash": "sha256:" + "2" * 64,
        },
        "image_path": image.name,
    }
    projection_path = tmp_path / "projection-set.json"
    projection_set = VisualProjectionSet.model_validate(
        {"source_revision": "r2", "projections": [projection]}
    ).with_computed_hashes()
    projection_path.write_text(
        json.dumps(projection_set.model_dump(mode="json"), ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return {
        "graph": current_path,
        "previous": previous_path,
        "predicates": predicates,
        "dfm": dfm,
        "projection": projection_path,
        "image": image,
    }


def _argv(
    files: dict[str, Path],
    out_dir: Path,
    *,
    previous: bool = True,
) -> list[str]:
    args = [
        "--graph",
        str(files["graph"]),
        "--projections",
        str(files["projection"]),
        "--design-predicates",
        str(files["predicates"]),
        "--dfm-report",
        str(files["dfm"]),
    ]
    args.extend(
        ["--previous-graph", str(files["previous"])] if previous else ["--no-previous-revision"]
    )
    args.extend(["--out-dir", str(out_dir), "--base-dir", str(files["graph"].parent)])
    return args


def test_previous_graph_diff_and_checklist(tmp_path: Path) -> None:
    files = _inputs(tmp_path)
    out_dir = tmp_path / "out"
    assert generate_review_package.main(_argv(files, out_dir)) == 0
    diff = json.loads((out_dir / "graph-diff.json").read_text(encoding="utf-8"))
    assert diff["status"] == "computed"
    assert diff["previous_revision"] == "r1"
    assert diff["current_revision"] == "r2"
    assert diff["nodes_added"]
    assert diff["nodes_removed"] == ["req.gd1-req-001"]
    assert diff["nodes_changed"][0]["changed_fields"] == ["attrs.text"]
    assert diff["edges_added"] == ["req.gd1-req-004->req.gd1-req-006"]
    assert diff["edges_removed"] == ["req.gd1-req-004->req.gd1-req-005"]
    package = json.loads((out_dir / "review-package.json").read_text(encoding="utf-8"))
    assert package["authority"] == "none"
    assert package["record_class"] == "L3"
    assert package["pass_evidence"] is False
    assert package["graph_diff_projection_id"] is None
    assert all(item["reviewer_decision"] == "pending" for item in package["checklist"])


def test_analysis_files_are_copied_and_added_to_checklist(tmp_path: Path) -> None:
    files = _inputs(tmp_path)
    out_dir = tmp_path / "out"
    analysis_path = tmp_path / "analysis"
    analysis_path.mkdir()
    for source in sorted(ANALYSIS_PATH.glob("*.json")):
        payload = json.loads(source.read_text(encoding="utf-8"))
        payload["revision"] = "r2"
        (analysis_path / source.name).write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    argv = [*_argv(files, out_dir), "--analysis", str(analysis_path)]
    assert generate_review_package.main(argv) == 0
    analysis_dir = out_dir / "analysis"
    assert (analysis_dir / "analysis-summary.md").is_file()
    assert (analysis_dir / "manifest.json").is_file()
    assert (analysis_dir / "spice_result.json").read_bytes() == (
        analysis_path / "spice-result.json"
    ).read_bytes()
    package = json.loads((out_dir / "review-package.json").read_text(encoding="utf-8"))
    analysis_items = [
        item for item in package["checklist"] if item["item_id"].startswith("analysis:")
    ]
    assert len(analysis_items) == 6
    assert [item["status"] for item in analysis_items] == [
        "checked",
        "checked",
        "checked",
        "checked",
        "unchecked",
        "unchecked",
    ]


def test_depends_on_only_changes_are_edges_not_node_changes() -> None:
    graph = json.loads(GRAPH_PATH.read_text(encoding="utf-8"))
    previous = json.loads(json.dumps(graph))
    current = json.loads(json.dumps(graph))
    previous["revision"] = "r1"
    current["revision"] = "r2"
    next(node for node in previous["nodes"] if node["id"] == "req.gd1-req-004")["depends_on"] = [
        "req.gd1-req-005"
    ]
    next(node for node in current["nodes"] if node["id"] == "req.gd1-req-004")["depends_on"] = [
        "req.gd1-req-006"
    ]
    diff = build_graph_diff(
        DesignGraph.model_validate(previous),
        DesignGraph.model_validate(current),
    )
    assert diff.nodes_changed == []


def test_no_previous_revision_is_unknown(tmp_path: Path) -> None:
    files = _inputs(tmp_path)
    out_dir = tmp_path / "out"
    generate_review_package.main(_argv(files, out_dir, previous=False))
    diff = json.loads((out_dir / "graph-diff.json").read_text(encoding="utf-8"))
    assert diff["status"] == "unknown"
    assert diff["reason"] == "previous revision not declared"
    assert diff["current_revision"] == "r2"
    assert diff["nodes_added"] == []


def test_json_output_is_deterministic(tmp_path: Path) -> None:
    files = _inputs(tmp_path)
    generate_review_package.main(_argv(files, tmp_path / "a"))
    generate_review_package.main(_argv(files, tmp_path / "b"))
    assert (tmp_path / "a/review-package.json").read_bytes() == (
        tmp_path / "b/review-package.json"
    ).read_bytes()


def test_projections_accept_several_paths_after_one_flag(tmp_path: Path) -> None:
    files = _inputs(tmp_path)
    second = tmp_path / "second-projection-set.json"
    second.write_bytes(files["projection"].read_bytes())
    argv = _argv(files, tmp_path / "out")
    argv.insert(argv.index("--projections") + 2, str(second))

    assert generate_review_package.main(argv) == 0
    package = json.loads((tmp_path / "out/review-package.json").read_text(encoding="utf-8"))
    assert len(package["projections"]) == 2


def test_previous_revision_declaration_is_required(tmp_path: Path) -> None:
    files = _inputs(tmp_path)
    args = _argv(files, tmp_path / "out")
    del args[args.index("--previous-graph") : args.index("--previous-graph") + 2]
    with pytest.raises(generate_review_package.DocumentGenerationError, match="exactly one"):
        generate_review_package.main(args)


def test_both_previous_revision_flags_fail(tmp_path: Path) -> None:
    files = _inputs(tmp_path)
    args = _argv(files, tmp_path / "out")
    args.append("--no-previous-revision")
    with pytest.raises(generate_review_package.DocumentGenerationError, match="exactly one"):
        generate_review_package.main(args)


def test_previous_graph_id_mismatch_fails(tmp_path: Path) -> None:
    files = _inputs(tmp_path)
    previous = json.loads(files["previous"].read_text(encoding="utf-8"))
    previous["graph_id"] = "other"
    files["previous"].write_text(json.dumps(previous) + "\n", encoding="utf-8")
    with pytest.raises(generate_review_package.DocumentGenerationError, match="graph"):
        generate_review_package.main(_argv(files, tmp_path / "out"))


def test_previous_same_revision_fails(tmp_path: Path) -> None:
    files = _inputs(tmp_path)
    previous = json.loads(files["previous"].read_text(encoding="utf-8"))
    previous["revision"] = "r2"
    files["previous"].write_text(json.dumps(previous) + "\n", encoding="utf-8")
    with pytest.raises(generate_review_package.DocumentGenerationError, match="same revision"):
        generate_review_package.main(_argv(files, tmp_path / "out"))


@pytest.mark.parametrize("name", ["predicates", "dfm"])
def test_input_revision_mismatch_fails(tmp_path: Path, name: str) -> None:
    files = _inputs(tmp_path)
    path = files[name]
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["target_revision"] = "r999"
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    with pytest.raises(generate_review_package.DocumentGenerationError, match="targets revision"):
        generate_review_package.main(_argv(files, tmp_path / "out"))


def test_projection_not_reproduced_fails(tmp_path: Path) -> None:
    files = _inputs(tmp_path)
    payload = json.loads(files["projection"].read_text(encoding="utf-8"))
    payload["projections"][0]["regeneration_check"] = {
        "status": "not_reproduced",
        "first_image_hash": "sha256:" + "2" * 64,
        "second_image_hash": "sha256:" + "3" * 64,
        "reason": "test",
    }
    payload["identity_hash"] = "unknown"
    payload["canonical_hash"] = "unknown"
    files["projection"].write_text(json.dumps(payload) + "\n", encoding="utf-8")
    with pytest.raises(generate_review_package.DocumentGenerationError, match="not reproduced"):
        generate_review_package.main(_argv(files, tmp_path / "out"))


def test_missing_projection_image_fails(tmp_path: Path) -> None:
    files = _inputs(tmp_path)
    files["image"].unlink()
    with pytest.raises(generate_review_package.DocumentGenerationError, match="is missing"):
        generate_review_package.main(_argv(files, tmp_path / "out"))
