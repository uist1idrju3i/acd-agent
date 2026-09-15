"""Tests for the KiCad 3D model bundler used by the tools image build."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_SCRIPT = (
    Path(__file__).resolve().parents[2] / "docker" / "bundle_kicad_3d_models.py"
)
_spec = importlib.util.spec_from_file_location("bundle_kicad_3d_models", _SCRIPT)
assert _spec is not None and _spec.loader is not None
bundle = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bundle)


def _manifest(tmp_path: Path, **overrides: object) -> Path:
    spec: dict[str, object] = {
        "schema": "acd.kicad-3d-models/2",
        "entries": [
            {
                "footprint_lib": "Resistor_SMD",
                "model_rel_path": "R_0603_1608Metric.step",
            }
        ],
        "missing_upstream": [
            {
                "footprint_lib": "Connector_USB",
                "model_rel_path": "USB_C_Receptacle_HRO_TYPE-C-31-M-12.step",
                "note": "Not shipped by kicad-packages3D; the footprint references it.",
            }
        ],
    }
    spec.update(overrides)
    path = tmp_path / "kicad-3d-models.json"
    path.write_text(json.dumps(spec), encoding="utf-8")
    return path


def _argv(manifest: Path, source_root: Path, dest: Path) -> list[str]:
    return [
        "--manifest",
        str(manifest),
        "--source-root",
        str(source_root),
        "--dest",
        str(dest),
    ]


def test_bundles_entries_and_asserts_missing_upstream(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source_root = tmp_path / "3dmodels"
    source = source_root / "Resistor_SMD.3dshapes" / "R_0603_1608Metric.step"
    source.parent.mkdir(parents=True)
    source.write_text("step-body", encoding="utf-8")
    dest = tmp_path / "dest"

    assert (
        bundle.main(_argv(_manifest(tmp_path), source_root, dest)) == 0
    )
    assert (
        dest / "Resistor_SMD.3dshapes" / "R_0603_1608Metric.step"
    ).read_text(encoding="utf-8") == "step-body"
    assert "bundled=1 missing_upstream=1" in capsys.readouterr().out


def test_missing_entry_source_is_fail_closed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source_root = tmp_path / "3dmodels"
    source_root.mkdir()
    capsys.readouterr()

    assert (
        bundle.main(_argv(_manifest(tmp_path), source_root, tmp_path / "dest"))
        == 2
    )
    assert "FAIL:" in capsys.readouterr().out


def test_present_missing_upstream_source_is_fail_closed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source_root = tmp_path / "3dmodels"
    entry = source_root / "Resistor_SMD.3dshapes" / "R_0603_1608Metric.step"
    entry.parent.mkdir(parents=True)
    entry.write_text("step-body", encoding="utf-8")
    upstream = (
        source_root
        / "Connector_USB.3dshapes"
        / "USB_C_Receptacle_HRO_TYPE-C-31-M-12.step"
    )
    upstream.parent.mkdir(parents=True)
    upstream.write_text("step-body", encoding="utf-8")
    capsys.readouterr()

    assert (
        bundle.main(_argv(_manifest(tmp_path), source_root, tmp_path / "dest"))
        == 2
    )
    assert "now shipped upstream" in capsys.readouterr().out


def test_unknown_schema_is_fail_closed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest = _manifest(tmp_path, schema="acd.kicad-3d-models/1")
    source_root = tmp_path / "3dmodels"
    source_root.mkdir()
    capsys.readouterr()

    assert bundle.main(_argv(manifest, source_root, tmp_path / "dest")) == 2
    assert "unsupported schema" in capsys.readouterr().out
