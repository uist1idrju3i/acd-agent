"""Tests for the model routing policy verification CLI."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[2]
POLICY = ROOT / "plugins/acd/model-policy.json"


def _invoke(
    *args: str, cwd: Path = ROOT
) -> tuple[subprocess.CompletedProcess[str], dict[str, object]]:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/verify_model_policy.py"), *args],
        capture_output=True,
        text=True,
        check=False,
        cwd=cwd,
    )
    return result, json.loads(result.stdout)


def test_cli_check_is_stable_and_cwd_independent(tmp_path: Path) -> None:
    before = hashlib.sha256(POLICY.read_bytes()).hexdigest()
    result, report = _invoke("--check")
    assert result.returncode == 0
    assert report["status"] == "pass"
    other, other_report = _invoke("--check", cwd=tmp_path)
    assert other.returncode == 0
    assert other_report == report
    assert hashlib.sha256(POLICY.read_bytes()).hexdigest() == before


def test_cli_canonical_hash_drift_returns_exit_two(tmp_path: Path) -> None:
    policy = tmp_path / "model-policy.json"
    value = json.loads(POLICY.read_text(encoding="utf-8"))
    value["canonical_hash"] = "sha256:" + "0" * 64
    policy.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    result, report = _invoke("--check", "--policy", str(policy), cwd=tmp_path)
    assert result.returncode == 2
    assert "Traceback" not in result.stderr
    assert report["status"] == "unknown"
    assert "api_key" not in result.stdout


def test_cli_same_agent_and_judge_model_returns_exit_two(tmp_path: Path) -> None:
    policy = tmp_path / "model-policy.json"
    value = json.loads(POLICY.read_text(encoding="utf-8"))
    value["bindings"][2]["model"] = value["bindings"][0]["model"]
    policy.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    result, report = _invoke("--check", "--policy", str(policy), cwd=tmp_path)
    assert result.returncode == 2
    assert "Traceback" not in result.stderr
    assert report["status"] == "unknown"
