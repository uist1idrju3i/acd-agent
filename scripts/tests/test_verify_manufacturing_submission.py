"""Tests for the manufacturing-submission verification entry point."""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from scripts import verify_manufacturing_submission
from tests.core.manufacturing_tree import GRAPH_PATH, build_submission_tree

from acd.core.manufacturing_submission import (
    manufacturing_submission_content_hash_payload,
)
from acd.schema.common import canonical_json_sha256


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


def _verdict_argv(verdict: Path, *extra: str) -> list[str]:
    return [
        "--verdict",
        str(verdict),
        "--graph",
        str(GRAPH_PATH),
        *extra,
    ]


def _refresh_verdict_hash(verdict: dict[str, Any]) -> None:
    verdict["content_sha256"] = canonical_json_sha256(
        manufacturing_submission_content_hash_payload(verdict)
    )


def _generate_verdict(root: Path, out: Path) -> dict[str, Any]:
    assert (
        verify_manufacturing_submission.main(
            _argv(root, out, "--require-authoritative")
        )
        == 0
    )
    return json.loads(out.read_text(encoding="utf-8"))


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


def test_cli_verdict_mode_passes(
    submission_root: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _copy_tree(submission_root, tmp_path / "verdict-pass")
    out = tmp_path / "verdict.json"
    _generate_verdict(root, out)

    code = verify_manufacturing_submission.main(
        _verdict_argv(out, "--require-authoritative")
    )

    assert code == 0
    assert "PASS: required_artifacts" in capsys.readouterr().out


def _mutate_failed_status(verdict: dict[str, Any]) -> None:
    checks = list(verdict["checks"])
    checks[0] = {**checks[0], "status": "fail"}
    verdict.update(
        {
            "status": "fail",
            "checks": checks,
            "reasons": [checks[0]["detail"]],
        }
    )


def _mutate_content_hash(verdict: dict[str, Any]) -> None:
    verdict["content_sha256"] = "sha256:" + "0" * 64


def _mutate_revision(verdict: dict[str, Any]) -> None:
    verdict["target_revision"] = "r999999"


def _mutate_authoritative(verdict: dict[str, Any]) -> None:
    verdict.update(
        {
            "authoritative": False,
            "evidence_class": {
                "electrical": "provisional",
                "mechanical": "provisional",
            },
        }
    )


@pytest.mark.parametrize(
    ("name", "mutate", "refresh_hash"),
    [
        ("status", _mutate_failed_status, True),
        ("content-hash", _mutate_content_hash, False),
        ("revision", _mutate_revision, True),
        ("authoritative", _mutate_authoritative, True),
    ],
)
def test_cli_verdict_mode_rejects_invalid_verdict(
    submission_root: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    name: str,
    mutate: Callable[[dict[str, Any]], None],
    refresh_hash: bool,
) -> None:
    root = _copy_tree(submission_root, tmp_path / name)
    out = tmp_path / f"{name}.json"
    verdict = _generate_verdict(root, out)
    mutate(verdict)
    if refresh_hash:
        _refresh_verdict_hash(verdict)
    out.write_text(
        json.dumps(verdict, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    code = verify_manufacturing_submission.main(
        _verdict_argv(out, "--require-authoritative")
    )

    assert code == 2
    assert "FAIL:" in capsys.readouterr().err


def test_cli_verdict_mode_rejects_broken_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "broken.json"
    out.write_text("{", encoding="utf-8")

    code = verify_manufacturing_submission.main(_verdict_argv(out))

    assert code == 2
    assert "FAIL:" in capsys.readouterr().err


def test_cli_verdict_mode_rejects_missing_path(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "missing.json"

    code = verify_manufacturing_submission.main(_verdict_argv(out))

    assert code == 2
    assert "FAIL:" in capsys.readouterr().err


def test_cli_verdict_mode_arguments_are_exclusive(tmp_path: Path) -> None:
    verdict = tmp_path / "verdict.json"
    with pytest.raises(SystemExit):
        verify_manufacturing_submission.main(
            [
                *_verdict_argv(verdict),
                "--board-out",
                str(tmp_path / "board"),
            ]
        )
    with pytest.raises(SystemExit):
        verify_manufacturing_submission.main(["--graph", str(GRAPH_PATH)])


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
