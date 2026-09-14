# pyright: reportMissingImports=false, reportUnknownVariableType=false, reportUnknownMemberType=false, reportUnknownArgumentType=false, reportUnknownParameterType=false, reportAttributeAccessIssue=false, reportOptionalMemberAccess=false

"""Library governance Skill and policy checks."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from acd.schema.design_graph import DesignGraph
from check_library_governance import (
    InputError,
    LibraryPolicy,
    check_library_governance,
    main,
)

ROOT = Path(__file__).resolve().parents[5]
GRAPH_PATH = ROOT / "fixtures" / "golden-design-1" / "graph.json"


def _policy() -> LibraryPolicy:
    return LibraryPolicy.model_validate(
        {
            "schema_version": "0.1",
            "policy_id": "test-policy",
            "footprint_rules": [
                {
                    "package_pattern": "*",
                    "pad_size_mm": {
                        "min_x": 0.9,
                        "max_x": 1.1,
                        "min_y": 0.9,
                        "max_y": 1.1,
                    },
                    "courtyard_required": True,
                    "courtyard_margin_mm": {"min": 0.4, "max": 0.6},
                    "origin": "centroid",
                    "origin_tolerance_mm": 0.01,
                    "allowed_layers": ["*.Cu", "*.Mask"],
                }
            ],
            "lib_table_rules": {
                "require_all_referenced_libraries": True,
                "allowed_sources": ["kicad-official", "project-local"],
            },
            "hash_pinning": {
                "require_footprint_sha256": True,
                "require_symbol_sha256": True,
            },
        }
    )


def _footprint() -> str:
    return """\
(footprint "Synthetic"
  (layer "F.Cu")
  (fp_rect (start -1 -1) (end 1 1) (layer "F.CrtYd"))
  (fp_rect (start -0.5 -0.5) (end 0.5 0.5) (layer "F.Fab"))
  (pad "1" thru_hole circle (at 0 0) (size 1 1) (layers "*.Cu" "*.Mask"))
)
"""


def _graph(tmp_path: Path, *, footprint: str | None = None) -> tuple[DesignGraph, Path, Path]:
    payload: dict[str, Any] = json.loads(GRAPH_PATH.read_text(encoding="utf-8"))
    footprint_path = tmp_path / "Synthetic.kicad_mod"
    footprint_path.write_text(footprint or _footprint(), encoding="utf-8")
    symbol_path = tmp_path / "Synthetic.kicad_sym"
    symbol_path.write_text("(kicad_symbol_lib (version 20231120))\n", encoding="utf-8")
    footprint_hash = f"sha256:{hashlib.sha256(footprint_path.read_bytes()).hexdigest()}"
    symbol_hash = f"sha256:{hashlib.sha256(symbol_path.read_bytes()).hexdigest()}"
    for node in payload["nodes"]:
        if node["kind"] != "electrical.component":
            continue
        attrs = node["attrs"]
        attrs["footprint"] = "Synthetic:Synthetic"
        attrs["footprint_file"] = str(footprint_path)
        attrs["footprint_sha256"] = footprint_hash
        attrs["symbol_file"] = str(symbol_path)
        attrs["symbol_sha256"] = symbol_hash
    return DesignGraph.model_validate(payload), footprint_path, symbol_path


def _table(tmp_path: Path, graph: DesignGraph) -> Path:
    names = sorted(
        {
            node.attrs["footprint"].split(":", 1)[0]
            for node in graph.nodes
            if node.kind == "electrical.component"
        }
    )
    table = tmp_path / "fp-lib-table"
    table.write_text(
        "(fp_lib_table\n"
        "  (version 7)\n"
        + "".join(
            (
                f'  (lib (name "{name}")(type "KiCad")'
                f'(uri "/usr/share/kicad/footprints/{name}.pretty")'
                '(options "")(descr ""))\n'
            )
            for name in names
        )
        + ")\n",
        encoding="utf-8",
    )
    return table


def test_gd1_synthetic_assets_pass_with_declared_table(tmp_path: Path) -> None:
    graph, _footprint_path, _symbol_path = _graph(tmp_path)
    _table(tmp_path, graph)
    report = check_library_governance(graph, _policy(), tmp_path)
    assert report["status"] == "pass"
    assert report["authority"] == "l2_review"


def test_pad_geometry_violation_fails(tmp_path: Path) -> None:
    graph, _footprint_path, _symbol_path = _graph(
        tmp_path,
        footprint=_footprint().replace("(size 1 1)", "(size 2 1)"),
    )
    report = check_library_governance(graph, _policy())
    assert report["status"] == "fail"
    assert any(item["check_id"] == "pad_geometry" for item in report["findings"])


def test_missing_courtyard_fails(tmp_path: Path) -> None:
    graph, _footprint_path, _symbol_path = _graph(
        tmp_path,
        footprint=_footprint().replace(
            '  (fp_rect (start -1 -1) (end 1 1) (layer "F.CrtYd"))\n',
            "",
        ),
    )
    report = check_library_governance(graph, _policy())
    assert report["status"] == "fail"
    assert any(item["check_id"] == "courtyard" for item in report["findings"])


def test_hash_mismatch_fails(tmp_path: Path) -> None:
    graph, footprint_path, _symbol_path = _graph(tmp_path)
    for node in graph.nodes:
        if node.kind == "electrical.component":
            node.attrs["footprint_sha256"] = "sha256:" + "0" * 64
            break
    report = check_library_governance(graph, _policy())
    assert report["status"] == "fail"
    assert footprint_path.is_file()
    assert any(item["check_id"] == "footprint_sha256" for item in report["findings"])


def test_undeclared_library_fails(tmp_path: Path) -> None:
    graph, _footprint_path, _symbol_path = _graph(tmp_path)
    _table(tmp_path, graph).write_text(
        (
            '(fp_lib_table (version 7) '
            '(lib (name "Other")(type "KiCad")'
            '(uri "/usr/share/kicad/footprints/Other.pretty")))\n'
        ),
        encoding="utf-8",
    )
    report = check_library_governance(graph, _policy(), tmp_path)
    assert report["status"] == "fail"
    assert any(item["check_id"] == "fp_lib_table" for item in report["findings"])


def test_disallowed_library_source_fails(tmp_path: Path) -> None:
    graph, _footprint_path, _symbol_path = _graph(tmp_path)
    _table(tmp_path, graph).write_text(
        '(fp_lib_table (version 7) '
        '(lib (name "Synthetic")(type "KiCad")'
        '(uri "/opt/vendor/footprints/Synthetic.pretty")))\n',
        encoding="utf-8",
    )
    report = check_library_governance(graph, _policy(), tmp_path)
    assert report["status"] == "fail"
    assert any(item["check_id"] == "fp_lib_source" for item in report["findings"])


def test_missing_footprint_is_unknown(tmp_path: Path) -> None:
    graph, footprint_path, _symbol_path = _graph(tmp_path)
    footprint_path.unlink()
    report = check_library_governance(graph, _policy())
    assert report["status"] == "unknown"
    assert any(item["status"] == "unknown" for item in report["findings"])


def test_report_is_deterministic(tmp_path: Path) -> None:
    graph, _footprint_path, _symbol_path = _graph(tmp_path)
    policy = _policy()
    first = check_library_governance(graph, policy)
    second = check_library_governance(graph, policy)
    assert first == second


def test_policy_revision_mismatch_is_input_error(tmp_path: Path) -> None:
    graph, _footprint_path, _symbol_path = _graph(tmp_path)
    policy = LibraryPolicy.model_validate(
        _policy().model_dump() | {"revision": "other-revision"}
    )
    try:
        check_library_governance(graph, policy)
    except InputError as exc:
        assert "revision" in str(exc)
    else:
        raise AssertionError("revision mismatch did not fail closed")


def test_malformed_graph_returns_cli_exit_two(tmp_path: Path) -> None:
    graph_path = tmp_path / "graph.json"
    policy_path = tmp_path / "policy.json"
    out_path = tmp_path / "report.json"
    graph_path.write_text("{", encoding="utf-8")
    policy_path.write_text(_policy().model_dump_json(), encoding="utf-8")
    assert (
        main(
            [
                "--graph",
                str(graph_path),
                "--policy",
                str(policy_path),
                "--out",
                str(out_path),
            ]
        )
        == 2
    )
    assert not out_path.exists()
