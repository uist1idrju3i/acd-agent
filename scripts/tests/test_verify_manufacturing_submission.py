"""Tests for the manufacturing-submission verification entry point."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from scripts import verify_manufacturing_submission
from tests.core.manufacturing_tree import GRAPH_PATH, build_submission_tree


@pytest.fixture(scope="module")
def submission_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("cli-submission-tree")
    build_submission_tree(root)
    return root


def _copy_tree(source: Path, destination: Path) -> Path:
    shutil.copytree(source, destination)
    return destination


def _argv(root: Path, out: Path, *extra: str) -> list[str]:
    return [
        "--board-out",
        str(root / "board"),
        "--enclosure-out",
        str(root / "enclosure"),
        "--graph",
        str(GRAPH_PATH),
        "--out",
        str(out),
        *extra,
    ]


def test_cli_passes_and_writes_verdict(
    submission_root: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _copy_tree(submission_root, tmp_path / "passing")
    out = tmp_path / "verdict" / "manufacturing-submission.json"

    code = verify_manufacturing_submission.main(
        _argv(root, out, "--require-authoritative")
    )

    assert code == 0
    verdict = json.loads(out.read_text(encoding="utf-8"))
    assert verdict["status"] == "pass"
    assert verdict["record_class"] == "L1"
    assert verdict["excluded_scope"] == ["quote_aggregation", "order_execution"]
    printed = capsys.readouterr().out
    assert "PASS: required_artifacts" in printed
    assert printed.count("\n") == len(verdict["checks"])


def test_cli_returns_two_on_broken_submission(
    submission_root: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _copy_tree(submission_root, tmp_path / "broken")
    (root / "board" / "gerbers" / "gd1-job.gbrjob").unlink()
    out = tmp_path / "verdict.json"

    code = verify_manufacturing_submission.main(_argv(root, out))

    assert code == 2
    assert out.is_file()
    verdict = json.loads(out.read_text(encoding="utf-8"))
    assert verdict["status"] == "fail"
    assert "required_artifacts" in {
        check["check_id"] for check in verdict["checks"] if check["status"] == "fail"
    }
    assert capsys.readouterr().out.count("\n") == len(verdict["checks"])
