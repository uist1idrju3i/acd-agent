"""Tests for the machine-generated final-report basis."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from acd.core.final_report_basis import (
    collect_design_values,
    collect_final_report_basis,
    collect_source_changes,
    render_final_report_basis,
)
from acd.schema.final_report_basis import FinalReportBasis

FIXTURE = Path("fixtures/golden-design-1/graph.json")
SCRIPT = (
    Path(__file__).resolve().parents[2] / "scripts" / "report_final_basis.py"
)


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return result.stdout.strip()


def _repo(tmp_path: Path) -> tuple[Path, str]:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "test@example.test")
    _git(root, "config", "user.name", "test")
    (root / ".gitignore").write_text(".openhands/\n", encoding="utf-8")
    (root / "README.md").write_text("x\n", encoding="utf-8")
    _git(root, "add", ".gitignore", "README.md")
    _git(root, "commit", "-qm", "initial")
    return root, _git(root, "rev-parse", "HEAD")


def _write_record(root: Path, revision: str) -> Path:
    record = root / ".openhands" / "bootstrap-record.json"
    record.parent.mkdir(parents=True)
    record.write_text(
        json.dumps({"resolved_revision": revision}), encoding="utf-8"
    )
    return record


def test_committed_source_changes_are_enumerated(tmp_path: Path) -> None:
    root, base = _repo(tmp_path)
    _write_record(root, base)
    (root / "src").mkdir()
    (root / "src" / "x.py").write_text("print('x')\n", encoding="utf-8")
    _git(root, "add", "src/x.py")
    _git(root, "commit", "-qm", "add x")
    head = _git(root, "rev-parse", "HEAD")

    section = collect_source_changes(root)
    assert section.status == "changed"
    assert section.committed_commits == [head]
    assert "src/x.py" in section.committed_log
    assert section.bootstrap_revision == base
    assert section.head_revision == head


def test_clean_tree_at_bootstrap_is_clean(tmp_path: Path) -> None:
    root, base = _repo(tmp_path)
    _write_record(root, base)
    section = collect_source_changes(root)
    assert section.status == "clean"
    assert section.committed_commits == []


def test_bootstrap_not_ancestor_is_unknown(tmp_path: Path) -> None:
    root, _base = _repo(tmp_path)
    _write_record(root, "0" * 40)
    section = collect_source_changes(root)
    assert section.status == "unknown"
    assert section.reason is not None


def test_missing_bootstrap_is_unknown(tmp_path: Path) -> None:
    root, _base = _repo(tmp_path)
    section = collect_source_changes(root)
    assert section.status == "unknown"
    assert "cannot be enumerated" in (section.reason or "")


def test_disagreeing_explicit_revision_is_unknown(tmp_path: Path) -> None:
    root, base = _repo(tmp_path)
    record = _write_record(root, base)
    section = collect_source_changes(
        root, bootstrap_record=record, bootstrap_revision="f" * 40
    )
    assert section.status == "unknown"


def test_spec_design_values(tmp_path: Path) -> None:
    spec = {
        "design_name": "demo",
        "components": [
            {
                "refdes": "R1",
                "attrs": {"value": "10k", "mpn": "M", "lcsc": "C1"},
                "pads": {"1": "net.vcc", "2": None},
            }
        ],
        "nets": [{"net_id": "net.vcc"}],
    }
    path = tmp_path / "spec.json"
    path.write_text(json.dumps(spec), encoding="utf-8")
    values = collect_design_values(path)
    assert values.source_kind == "spec"
    assert values.design_name == "demo"
    (component,) = values.components
    assert component.refdes == "R1"
    assert component.value == "10k"
    assert component.pads == {"1": "net.vcc", "2": None}
    (net,) = values.nets
    assert net.net_id == "net.vcc"
    assert net.connections == ["R1.1"]


def test_gd1_graph_design_values() -> None:
    values = collect_design_values(FIXTURE)
    assert values.source_kind == "graph"
    u1 = next(c for c in values.components if c.refdes == "U1")
    assert u1.value == "ESP32-C3-MINI-1-N4"
    gnd = next(n for n in values.nets if n.net_id == "net.gnd")
    assert "U1.1" in gnd.connections


def test_render_contains_unverified_evidence_line(tmp_path: Path) -> None:
    root, base = _repo(tmp_path)
    _write_record(root, base)
    report = collect_final_report_basis(root)
    text = render_final_report_basis(report)
    assert "authoritative Evidence: unverified" in text
    assert "status: clean" in text


def _load_cli() -> Any:
    spec = importlib.util.spec_from_file_location("report_final_basis", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_cli_exit_codes_and_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cli = _load_cli()
    root, base = _repo(tmp_path)
    _write_record(root, base)
    assert cli.main(["--root", str(root)]) == 0
    capsys.readouterr()
    assert cli.main(["--root", str(root), "--json"]) == 0
    parsed = FinalReportBasis.model_validate_json(capsys.readouterr().out)
    assert parsed.status == "pass"

    empty = tmp_path / "empty"
    empty.mkdir()
    assert cli.main(["--root", str(empty)]) == 1
    output = capsys.readouterr().out
    assert "status: unknown" in output
