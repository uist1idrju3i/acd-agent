"""Negative tests for the Skill package skew contract."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from scripts import verify_skill_package_ref as checker


def _run_git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True, check=True
    )
    return completed.stdout.strip()


def _repository(tmp_path: Path, *, symbol: bool = True) -> Path:
    root = tmp_path / "repo"
    (root / "src/acd/schema").mkdir(parents=True)
    (root / "src/acd/__init__.py").write_text("", encoding="utf-8")
    (root / "src/acd/schema/__init__.py").write_text("", encoding="utf-8")
    (root / "src/acd/schema/design_graph.py").write_text(
        'from typing import Literal\nNodeKind = Literal["requirement"]\n',
        encoding="utf-8",
    )
    (root / "src/acd/foo.py").write_text(
        "thing = 1\n" if symbol else "other = 1\n", encoding="utf-8"
    )
    script = root / "plugins/acd/skills/example/scripts/example.py"
    script.parent.mkdir(parents=True)
    script.write_text(
        "# /// script\n"
        '# requires-python = ">=3.12"\n'
        "# dependencies = [\n"
        '#     "acd @ git+https://github.com/uist1idrju3i/acd-agent@REF",\n'
        "# ]\n"
        "# ///\n"
        "from acd.foo import thing\n",
        encoding="utf-8",
    )
    (root / "plugins/acd/skills/acd-package-ref.txt").write_text(
        "REF\n", encoding="utf-8"
    )
    (root / "pyproject.toml").write_text(
        '[project]\nrequires-python = ">=3.12"\n', encoding="utf-8"
    )
    fixture = root / "fixtures/example/graph.json"
    fixture.parent.mkdir(parents=True)
    fixture.write_text(
        json.dumps({"nodes": [{"kind": "requirement"}], "edges": []}), encoding="utf-8"
    )
    _run_git(root, "init", "-q")
    _run_git(root, "branch", "-M", "main")
    _run_git(root, "config", "user.email", "test@example.invalid")
    _run_git(root, "config", "user.name", "Test")
    _run_git(
        root,
        "add",
        "src",
        "plugins/acd/skills",
        "fixtures",
        "pyproject.toml",
    )
    _run_git(root, "commit", "-qm", "base")
    commit = _run_git(root, "rev-parse", "HEAD")
    ref = root / "plugins/acd/skills/acd-package-ref.txt"
    ref.write_text(commit + "\n", encoding="utf-8")
    script.write_text(
        script.read_text(encoding="utf-8").replace("REF", commit), encoding="utf-8"
    )
    _run_git(root, "add", "plugins/acd/skills")
    _run_git(root, "commit", "-qm", "metadata")
    ref.write_text(commit + "\n", encoding="utf-8")
    assert checker.write_contract(root) == []
    return root


def test_real_repository_contract_is_valid() -> None:
    assert checker.verify_repository() == []


def test_older_ref_than_fixture_schema_fails_closed(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    schema = root / "src/acd/schema/design_graph.py"
    schema.write_text(
        'from typing import Literal\n'
        'NodeKind = Literal["requirement", "firmware.state"]\n',
        encoding="utf-8",
    )
    fixture = root / "fixtures/example/graph.json"
    fixture.write_text(
        json.dumps({"nodes": [{"kind": "firmware.state"}], "edges": []}),
        encoding="utf-8",
    )
    errors = checker.verify_repository(root)
    assert any("src/acd/schema differs" in error for error in errors)


def test_fixture_kind_absent_from_pinned_schema_fails_closed(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    fixture = root / "fixtures/example/graph.json"
    fixture.write_text(
        json.dumps({"nodes": [{"kind": "missing.kind"}], "edges": []}),
        encoding="utf-8",
    )
    errors = checker.verify_repository(root)
    assert any(
        "fixture kinds are absent from pinned schema" in error for error in errors
    )


def test_unresolvable_ref_fails_closed(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    (root / "plugins/acd/skills/acd-package-ref.txt").write_text(
        "0" * 40 + "\n", encoding="utf-8"
    )
    assert any("does not resolve" in error for error in checker.verify_repository(root))


def test_non_ancestor_ref_fails_closed(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    _run_git(root, "switch", "-c", "side")
    (root / "side.txt").write_text("side\n", encoding="utf-8")
    _run_git(root, "add", "side.txt")
    _run_git(root, "commit", "-qm", "side")
    side = _run_git(root, "rev-parse", "HEAD")
    _run_git(root, "switch", "main")
    (root / "plugins/acd/skills/acd-package-ref.txt").write_text(
        side + "\n", encoding="utf-8"
    )
    assert any("not an ancestor" in error for error in checker.verify_repository(root))


def test_missing_pinned_api_symbol_fails_closed(tmp_path: Path) -> None:
    root = _repository(tmp_path, symbol=False)
    assert any("pinned API symbol" in error for error in checker.verify_repository(root))


def test_contract_drift_fails_closed(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    contract = root / "plugins/acd/skills/acd-package-contract.json"
    document = json.loads(contract.read_text(encoding="utf-8"))
    document["fixture_kinds"] = []
    contract.write_text(json.dumps(document), encoding="utf-8")
    assert any("contract drift" in error for error in checker.verify_repository(root))
