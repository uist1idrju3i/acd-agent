"""Tests for the core/Skill import boundary check."""

from __future__ import annotations

from pathlib import Path

from scripts.verify_import_boundaries import build_report, main

ROOT = Path(__file__).parents[2]


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _clean_repo(root: Path) -> None:
    _write(root, "src/acd/core/a.py", "from acd.schema import DesignGraph\n")
    _write(root, "scripts/verify_x.py", "import json\n")
    _write(root, "plugins/acd/skills/acd-one/scripts/one_lib.py", "X = 1\n")
    _write(root, "plugins/acd/skills/acd-one/scripts/one_cli.py", "import one_lib\nimport acd\n")
    _write(root, "plugins/acd/skills/acd-two/scripts/two_lib.py", "Y = 2\n")
    _write(root, "plugins/acd/hooks/scripts/stop.py", "import json\n")
    _write(root, "plugins/acd/skills/acd-one/tests/test_one.py", "import two_lib\n")


def test_clean_tree_passes(tmp_path: Path) -> None:
    _clean_repo(tmp_path)
    report = build_report(tmp_path)
    assert report.status == "pass"
    assert report.record_class == "L3"
    assert report.pass_evidence is False
    assert report.violations == []
    assert main(["--root", str(tmp_path)]) == 0


def test_core_importing_skill_module_fails(tmp_path: Path) -> None:
    _clean_repo(tmp_path)
    _write(tmp_path, "src/acd/core/b.py", "from one_lib import X\n")
    _write(tmp_path, "scripts/bridge.py", "import plugins.acd.skills\n")
    report = build_report(tmp_path)
    assert [(v.path, v.rule) for v in report.violations] == [
        ("scripts/bridge.py", "core_imports_skill"),
        ("src/acd/core/b.py", "core_imports_skill"),
    ]
    assert main(["--root", str(tmp_path)]) == 1


def test_core_sys_path_mutation_fails(tmp_path: Path) -> None:
    _clean_repo(tmp_path)
    _write(tmp_path, "src/acd/core/c.py", "import sys\nsys.path.insert(0, 'x')\n")
    report = build_report(tmp_path)
    assert [v.rule for v in report.violations] == ["core_mutates_sys_path"]


def test_skill_importing_other_skill_fails(tmp_path: Path) -> None:
    _clean_repo(tmp_path)
    _write(tmp_path, "plugins/acd/skills/acd-two/scripts/two_cli.py", "from one_lib import X\n")
    report = build_report(tmp_path)
    assert len(report.violations) == 1
    violation = report.violations[0]
    assert violation.rule == "skill_imports_other_skill"
    assert violation.path == "plugins/acd/skills/acd-two/scripts/two_cli.py"
    assert "acd-one" in violation.detail


def test_repository_respects_boundary() -> None:
    assert build_report(ROOT).violations == []
