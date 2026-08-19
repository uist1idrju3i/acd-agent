"""Tests for the KiCad visual projection adapter."""

from __future__ import annotations

import stat
from pathlib import Path

import pytest

from acd.adapters.kicad.cli import KicadCli
from acd.adapters.kicad.visual_projection import KicadVisualRenderer
from acd.core.process import ExternalToolError

_FAKE_KICAD = """\
#!/usr/bin/env python3
import os
import pathlib
import sys

if sys.argv[1:] == ["version"]:
    print("10.0.5")
    raise SystemExit(0)

output = pathlib.Path(sys.argv[sys.argv.index("-o") + 1])
output.parent.mkdir(parents=True, exist_ok=True)
extra = (
    '<path d="different"/>'
    if os.getenv("FAKE_MISMATCH") and "reproduced" in output.name
    else '<path d="same"/>'
)
output.write_text(
    '<svg width="29.9974mm" height="24.9936mm" '
    'viewBox="0.0000 0.0000 29.9974 24.9936">'
    f'<title>SVG Image created as {output.name} date 2026-08-19T03:45:00Z </title>'
    + extra + '</svg>'
)
"""


def _executable(tmp_path: Path) -> Path:
    executable = tmp_path / "fake-kicad-cli"
    executable.write_text(_FAKE_KICAD)
    executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
    return executable


def test_renderer_reproduces_and_records_measured_provenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    Path("gd1.kicad_sch").write_text("schematic")
    renderer = KicadVisualRenderer(KicadCli(str(_executable(tmp_path))))

    record = renderer.render(
        projection_id="gd1-schematic",
        projection_type="schematic_view",
        domain="electrical",
        source_revision="r8",
        source=Path("gd1.kicad_sch"),
        output_path=Path("schematic.svg"),
    )

    assert record.image_hash.startswith("sha256:")
    assert record.regeneration_check.status == "reproduced"
    assert record.resolution.width == "29.9974mm"
    assert record.image_path == "schematic.svg"
    assert Path("schematic.reproduced.svg").is_file()


def test_renderer_stops_on_regeneration_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("FAKE_MISMATCH", "1")
    Path("gd1.kicad_sch").write_text("schematic")
    renderer = KicadVisualRenderer(KicadCli(str(_executable(tmp_path))))

    with pytest.raises(ExternalToolError, match="regeneration hash mismatch"):
        renderer.render(
            projection_id="gd1-schematic",
            projection_type="schematic_view",
            domain="electrical",
            source_revision="r8",
            source=Path("gd1.kicad_sch"),
            output_path=Path("schematic.svg"),
        )


def test_renderer_supports_layered_layout_view(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    Path("gd1.kicad_pcb").write_text("board")
    renderer = KicadVisualRenderer(KicadCli(str(_executable(tmp_path))))

    record = renderer.render(
        projection_id="gd1-front-copper",
        projection_type="layered_layout_view",
        domain="electrical",
        source_revision="r8",
        source=Path("gd1.kicad_pcb"),
        output_path=Path("front-copper.svg"),
        layer="F.Cu",
    )

    assert record.projection_type == "layered_layout_view"
    assert record.input_files[0].path == "gd1.kicad_pcb"


def test_renderer_absent_executable_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(ExternalToolError, match="version probe failed"):
        KicadCli(str(tmp_path / "missing-kicad-cli")).version()


def test_renderer_requires_relative_paths(tmp_path: Path) -> None:
    source = tmp_path / "gd1.kicad_sch"
    source.write_text("schematic")
    with pytest.raises(ExternalToolError, match="repository-relative"):
        KicadVisualRenderer().render(
            projection_id="gd1-schematic",
            projection_type="schematic_view",
            domain="electrical",
            source_revision="r8",
            source=source,
            output_path=Path("schematic.svg"),
        )
