"""Firmware security CLI contract tests."""

from __future__ import annotations

from pathlib import Path

from scripts.check_fw_security import main

ROOT = Path("fixtures/golden-design-1")


def test_security_cli_passes_and_writes_result(tmp_path: Path) -> None:
    out = tmp_path / "gate.json"
    code = main(
        [
            "--declaration",
            str(ROOT / "fw-security.json"),
            "--sdkconfig",
            str(ROOT / "fw-security-sdkconfig"),
            "--partitions",
            str(ROOT / "fw-security-partitions.csv"),
            "--graph",
            str(ROOT / "graph.json"),
            "--out",
            str(out),
        ]
    )
    assert code == 0
    assert '"status": "pass"' in out.read_text(encoding="utf-8")


def test_security_cli_revision_mismatch_is_input_error(tmp_path: Path) -> None:
    graph = tmp_path / "graph.json"
    graph.write_text(
        (ROOT / "graph.json")
        .read_text(encoding="utf-8")
        .replace('"revision": "r1"', '"revision": "r2"', 1),
        encoding="utf-8",
    )
    code = main(
        [
            "--declaration",
            str(ROOT / "fw-security.json"),
            "--sdkconfig",
            str(ROOT / "fw-security-sdkconfig"),
            "--partitions",
            str(ROOT / "fw-security-partitions.csv"),
            "--graph",
            str(graph),
            "--out",
            str(tmp_path / "gate.json"),
        ]
    )
    assert code == 2
