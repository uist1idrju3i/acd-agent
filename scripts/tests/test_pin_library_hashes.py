"""Tests for the spec library-hash pinning CLI."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, cast


def _spec(components: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "design_name": "pin-test",
        "revision": "r1",
        "components": components,
        "nets": [{"net_id": "net.gnd", "attrs": {"name": "GND"}}],
        "custom_key": {"keep": [1, 2, 3]},
    }


def _component(symbol: Path, footprint: Path) -> dict[str, Any]:
    return {
        "refdes": "D1",
        "attrs": {
            "mpn": "LED-1",
            "symbol": "Device:LED",
            "symbol_file": str(symbol),
            "footprint": "Lib:FP",
            "footprint_file": str(footprint),
        },
        "pads": {"1": "net.gnd"},
    }


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "scripts/pin_library_hashes.py", *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def test_unpinned_assets_are_reported_and_written(tmp_path: Path) -> None:
    symbol = tmp_path / "Device.kicad_sym"
    footprint = tmp_path / "LED.kicad_mod"
    symbol.write_text("(kicad_symbol_lib)", encoding="utf-8")
    footprint.write_text("(footprint)", encoding="utf-8")
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(
        json.dumps(_spec([_component(symbol, footprint)])), encoding="utf-8"
    )

    check = _run("--spec", str(spec_path))
    assert check.returncode == 1
    assert "unpinned" in check.stdout

    written = _run("--spec", str(spec_path), "--write")
    assert written.returncode == 0, written.stdout + written.stderr
    assert "match" in written.stdout

    spec = cast(
        dict[str, Any], json.loads(spec_path.read_text(encoding="utf-8"))
    )
    attrs = cast(
        dict[str, Any],
        cast(list[Any], spec["components"])[0]["attrs"],
    )
    assert attrs["symbol_sha256"] == _sha256(symbol)
    assert attrs["footprint_sha256"] == _sha256(footprint)
    # keys outside components are preserved verbatim
    assert spec["custom_key"] == {"keep": [1, 2, 3]}
    assert spec["design_name"] == "pin-test"


def test_missing_file_fails_and_points_at_container(tmp_path: Path) -> None:
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(
        json.dumps(
            _spec([_component(tmp_path / "absent.kicad_sym", tmp_path / "x")])
        ),
        encoding="utf-8",
    )

    result = _run("--spec", str(spec_path))

    assert result.returncode == 1
    assert "missing" in result.stdout
    assert "run_in_workspace.py" in result.stdout
    assert "absent.kicad_sym" in result.stdout


def test_mismatch_without_write_fails_closed(tmp_path: Path) -> None:
    symbol = tmp_path / "Device.kicad_sym"
    symbol.write_text("(kicad_symbol_lib)", encoding="utf-8")
    component = _component(symbol, symbol)
    cast(dict[str, Any], component["attrs"])["symbol_sha256"] = (
        "sha256:" + "0" * 64
    )
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps(_spec([component])), encoding="utf-8")

    result = _run("--spec", str(spec_path))

    assert result.returncode == 1
    assert "mismatch" in result.stdout


def test_library_root_override_resolves_relative_paths(tmp_path: Path) -> None:
    root = tmp_path / "libroot"
    (root / "pkg").mkdir(parents=True)
    symbol = root / "pkg" / "Device.kicad_sym"
    symbol.write_text("(kicad_symbol_lib)", encoding="utf-8")
    component = {
        "refdes": "D1",
        "attrs": {"symbol_file": "pkg/Device.kicad_sym"},
        "pads": {},
    }
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(
        json.dumps(_spec([component])), encoding="utf-8"
    )

    result = _run(
        "--spec", str(spec_path), "--library-root", str(root), "--write"
    )

    assert result.returncode == 0, result.stdout + result.stderr
    spec = cast(
        dict[str, Any], json.loads(spec_path.read_text(encoding="utf-8"))
    )
    attrs = cast(
        dict[str, Any], cast(list[Any], spec["components"])[0]["attrs"]
    )
    assert attrs["symbol_sha256"] == _sha256(symbol)
