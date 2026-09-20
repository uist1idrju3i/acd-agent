"""Tests for the Ruff complexity ratchet."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts.verify_ruff_ratchet import RatchetError, build_report, main, run_ruff

ROOT = Path(__file__).parents[2]

# Seven positional parameters trigger PLR0913 (default max-args is 5).
_TOO_MANY_ARGS = "def f(a, b, c, d, e, f, g):\n    return a\n"
# Comparing against a bare literal triggers PLR2004.
_MAGIC_VALUE = "def g(x):\n    return x > 42\n"


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_baseline(root: Path, entries: list[dict[str, object]]) -> Path:
    path = root / "contracts/ruff-ratchet-baseline.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "record_class": "L3",
                "pass_evidence": False,
                "rules": ["C901", "PLR0911", "PLR0912", "PLR0913", "PLR0915", "PLR2004"],
                "scan_paths": ["src", "scripts", "plugins"],
                "entries": entries,
            }
        ),
        encoding="utf-8",
    )
    return path


def test_run_ruff_counts_by_path_and_rule(tmp_path: Path) -> None:
    _write(tmp_path, "src/mod.py", _TOO_MANY_ARGS + _MAGIC_VALUE)
    _write(tmp_path, "src/tests/test_mod.py", _MAGIC_VALUE)
    counts = run_ruff(tmp_path, ("PLR0913", "PLR2004"), ("src",))
    assert counts == {("src/mod.py", "PLR0913"): 1, ("src/mod.py", "PLR2004"): 1}


def test_write_then_check_passes(tmp_path: Path) -> None:
    _write(tmp_path, "src/mod.py", _TOO_MANY_ARGS)
    baseline = tmp_path / "contracts/ruff-ratchet-baseline.json"
    assert main(["--write", "--root", str(tmp_path), "--baseline", str(baseline)]) == 0
    recorded = json.loads(baseline.read_text(encoding="utf-8"))
    assert recorded["entries"] == [{"path": "src/mod.py", "rule": "PLR0913", "count": 1}]
    assert main(["--check", "--root", str(tmp_path), "--baseline", str(baseline)]) == 0


def test_new_finding_fails_closed(tmp_path: Path) -> None:
    _write(tmp_path, "src/mod.py", _TOO_MANY_ARGS + _MAGIC_VALUE)
    baseline = _write_baseline(tmp_path, [{"path": "src/mod.py", "rule": "PLR0913", "count": 1}])
    report = build_report(tmp_path, baseline)
    assert report.status == "fail"
    assert report.regressions == ["src/mod.py: PLR2004 0 -> 1"]
    assert main(["--check", "--root", str(tmp_path), "--baseline", str(baseline)]) == 1


def test_stale_baseline_fails_until_rewritten(tmp_path: Path) -> None:
    _write(tmp_path, "src/mod.py", _TOO_MANY_ARGS)
    baseline = _write_baseline(
        tmp_path,
        [
            {"path": "src/mod.py", "rule": "PLR0913", "count": 1},
            {"path": "src/mod.py", "rule": "PLR2004", "count": 3},
        ],
    )
    report = build_report(tmp_path, baseline)
    assert report.status == "fail"
    assert report.regressions == []
    assert report.improvements == ["src/mod.py: PLR2004 3 -> 0"]
    assert main(["--check", "--root", str(tmp_path), "--baseline", str(baseline)]) == 1


def test_baseline_with_other_rules_is_rejected(tmp_path: Path) -> None:
    _write(tmp_path, "src/mod.py", _TOO_MANY_ARGS)
    baseline = _write_baseline(tmp_path, [])
    data = json.loads(baseline.read_text(encoding="utf-8"))
    data["rules"] = ["C901"]
    baseline.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(RatchetError, match="rerun --write"):
        build_report(tmp_path, baseline)
    assert main(["--check", "--root", str(tmp_path), "--baseline", str(baseline)]) == 1


def test_repository_baseline_matches_source() -> None:
    report = build_report(ROOT, ROOT / "contracts" / "ruff-ratchet-baseline.json")
    assert report.status == "pass", {
        "regressions": report.regressions,
        "improvements": report.improvements,
    }
