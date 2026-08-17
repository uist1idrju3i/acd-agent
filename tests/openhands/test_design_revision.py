"""Design Graph revision CLI tests."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from acd.openhands.design_revision import resolve

ROOT = Path(__file__).parents[2]


def _graph(tmp_path: Path) -> Path:
    path = tmp_path / "graph.json"
    path.write_text(
        (ROOT / "fixtures/golden-design-1/graph.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    return path


def test_resolve_valid_graph(tmp_path: Path) -> None:
    assert resolve([_graph(tmp_path)]) == "r1"


def test_resolve_rejects_invalid_json_and_schema(tmp_path: Path) -> None:
    path = tmp_path / "graph.json"
    path.write_text("{", encoding="utf-8")
    assert resolve([path]) is None
    path.write_text(json.dumps({"revision": "r1"}), encoding="utf-8")
    assert resolve([path]) is None


def test_resolve_rejects_missing_and_non_unique_paths(tmp_path: Path) -> None:
    first = _graph(tmp_path)
    missing = tmp_path / "missing.json"
    assert resolve([missing]) is None
    assert resolve([first, missing]) is None


def test_cli_prints_only_valid_revision(tmp_path: Path) -> None:
    graph = _graph(tmp_path)
    env = os.environ.copy()
    valid = subprocess.run(
        [
            "uv",
            "run",
            "--project",
            str(ROOT),
            "acd-design-revision",
            str(graph),
        ],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert valid.returncode == 0
    assert valid.stdout.strip() == "r1"
    invalid = subprocess.run(
        [
            "uv",
            "run",
            "--project",
            str(ROOT),
            "acd-design-revision",
            str(tmp_path / "missing.json"),
        ],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert invalid.returncode != 0
    assert invalid.stdout == ""
