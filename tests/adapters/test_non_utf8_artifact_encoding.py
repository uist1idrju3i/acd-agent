"""Regression coverage for generated artifacts under a non-UTF-8 locale."""
# pyright: reportMissingTypeStubs=false,reportPrivateUsage=false

from __future__ import annotations

import io
import json
import zipfile
from hashlib import sha256
from pathlib import Path

from acd.adapters.kicad.fab import jlcpcb_bom_csv, jlcpcb_cpl_csv, parse_pos_csv
from acd.adapters.kicad.fab.archive import deterministic_zip, zip_content_hash
from acd.adapters.kicad.reload import normalize_member
from acd.core.cad_normalize import normalize_3mf, normalize_step, normalize_stl
from acd.core.electrical import BoardView, ComponentView, ElectricalLane, LibraryPin
from acd.core.manufacturing_submission import (
    _fitted_refdes_from_bom,
    _fitted_refdes_from_cpl,
)
from tests.helpers.locale import run_under_c_locale


def _board() -> BoardView:
    return BoardView(
        "board",
        20.0,
        15.0,
        2,
        1.6,
        "mm",
        "lower-left",
        "up",
        0.15,
        0.15,
        0.2,
        0.4,
        0.2,
        False,
    )


def _component() -> ComponentView:
    library = LibraryPin(
        symbol="Device:C",
        symbol_file="symbol.kicad_sym",
        symbol_source="fixture",
        symbol_source_ref="fixture",
        symbol_sha256="sha256:" + "a" * 64,
        footprint="Capacitor_SMD:C_0603_1608Metric",
        footprint_file="capacitor.kicad_mod",
        footprint_source="fixture",
        footprint_source_ref="fixture",
        footprint_sha256="sha256:" + "b" * 64,
    )
    return ComponentView(
        node_id="c1",
        refdes="C1",
        value="筐体",
        mpn="C-0603",
        lcsc="C123",
        jlcpcb_class="Basic",
        assembly="fitted",
        library=library,
    )


def _write_fab_fixture(tmp_path: Path) -> dict[str, str]:
    component = _component()
    lane = ElectricalLane((_component(),), (), (), _board())
    bom_path = tmp_path / "board-bom.csv"
    bom_path.write_text(jlcpcb_bom_csv(lane), encoding="utf-8")
    cpl_path = tmp_path / "board-cpl.csv"
    cpl_path.write_text(
        jlcpcb_cpl_csv(
            (
                {
                    "Ref": component.refdes,
                    "PosX": "1.0",
                    "PosY": "-2.0",
                    "Rot": "90",
                    "Side": "top",
                },
            ),
            {"C1"},
        ),
        encoding="utf-8",
    )
    pos_path = tmp_path / "board.pos.csv"
    pos_path.write_text(
        "Ref,PosX,PosY,Rot,Side\nC1,1.0,-2.0,90,top\n",
        encoding="utf-8",
    )
    package_path = tmp_path / "fab-package.json"
    package_path.write_text(
        json.dumps({"name": "筐体", "files": [bom_path.name, cpl_path.name]}, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )
    gbrjob_path = tmp_path / "board-job.gbrjob"
    gbrjob_path.write_text(
        json.dumps(
            {
                "Header": {"CreationDate": "2026-01-01", "Comment": "筐体"},
                "FilesAttributes": [{"Path": "board-F_Cu.gtl"}],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    archive_path = tmp_path / "board-gerbers.zip"
    deterministic_zip(archive_path, (gbrjob_path,), tmp_path)
    return {
        "bom": bom_path.name,
        "cpl": cpl_path.name,
        "pos": pos_path.name,
        "package": package_path.name,
        "gbrjob": gbrjob_path.name,
        "archive": archive_path.name,
    }


def _fab_result(root: Path, names: dict[str, str]) -> dict[str, object]:
    bom = root / names["bom"]
    cpl = root / names["cpl"]
    pos = root / names["pos"]
    package = root / names["package"]
    gbrjob = root / names["gbrjob"]
    return {
        "bom": sorted(_fitted_refdes_from_bom(bom)),
        "cpl": sorted(_fitted_refdes_from_cpl(cpl)),
        "position": [dict(row) for row in parse_pos_csv(pos)],
        "package": json.loads(package.read_text(encoding="utf-8")),
        "gbrjob": sha256(normalize_member(gbrjob.read_bytes(), gbrjob.name)).hexdigest(),
        "zip": zip_content_hash(root / names["archive"]),
    }


def test_fab_artifacts_are_locale_independent(tmp_path: Path) -> None:
    names = _write_fab_fixture(tmp_path)
    expected = _fab_result(tmp_path, names)
    child_code = """
import json
import sys
from hashlib import sha256
from pathlib import Path
from acd.adapters.kicad.fab import parse_pos_csv
from acd.adapters.kicad.fab.archive import zip_content_hash
from acd.adapters.kicad.reload import normalize_member
from acd.core.manufacturing_submission import _fitted_refdes_from_bom, _fitted_refdes_from_cpl
root = Path(sys.argv[1])
names = json.loads(sys.argv[2])
bom = root / names["bom"]
cpl = root / names["cpl"]
pos = root / names["pos"]
package = root / names["package"]
gbrjob = root / names["gbrjob"]
result = {
    "bom": sorted(_fitted_refdes_from_bom(bom)),
    "cpl": sorted(_fitted_refdes_from_cpl(cpl)),
    "position": [dict(row) for row in parse_pos_csv(pos)],
    "package": json.loads(package.read_text(encoding="utf-8")),
    "gbrjob": sha256(normalize_member(gbrjob.read_bytes(), gbrjob.name)).hexdigest(),
    "zip": zip_content_hash(root / names["archive"]),
}
print(json.dumps(result, ensure_ascii=True, sort_keys=True))
"""
    completed = run_under_c_locale(child_code, tmp_path, Path(json.dumps(names)))
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == expected


def _write_enclosure_fixture(tmp_path: Path) -> dict[str, str]:
    step_path = tmp_path / "enclosure.step"
    step_path.write_bytes(
        b"FILE_NAME('Open CASCADE Shape Model','2026-\xe7\xad\x90\xe4\xbd\x93');\n"
    )
    stl_path = tmp_path / "enclosure.stl"
    stl_path.write_text(
        "solid enclosure\n"
        "facet normal 0 0 1\nouter loop\n"
        "vertex 0 0 0\nvertex 1 0 0\nvertex 0 1 0\n"
        "endloop\nendfacet\nendsolid enclosure\n",
        encoding="ascii",
    )
    model = (
        '<model name="筐体" p:UUID="01234567-89ab-cdef-0123-456789abcdef"/>'
    ).encode()
    model_zip = io.BytesIO()
    with zipfile.ZipFile(model_zip, "w") as archive:
        archive.writestr("3D/3dmodel.model", model)
    model_path = tmp_path / "enclosure.3mf"
    model_path.write_bytes(model_zip.getvalue())
    manifest_path = tmp_path / "enclosure-artifacts.json"
    manifest_path.write_text(
        json.dumps(
            {"name": "筐体", "artifacts": [step_path.name, model_path.name]},
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    return {
        "step": step_path.name,
        "stl": stl_path.name,
        "model": model_path.name,
        "manifest": manifest_path.name,
    }


def _enclosure_result(root: Path, names: dict[str, str]) -> dict[str, object]:
    step = root / names["step"]
    stl = root / names["stl"]
    model = root / names["model"]
    manifest = root / names["manifest"]
    return {
        "step": sha256(normalize_step(step.read_bytes())).hexdigest(),
        "model": sha256(normalize_3mf(model.read_bytes())).hexdigest(),
        "stl": sha256(normalize_stl(stl.read_bytes())).hexdigest(),
        "manifest": json.loads(manifest.read_text(encoding="utf-8")),
    }


def test_enclosure_artifacts_are_locale_independent(tmp_path: Path) -> None:
    names = _write_enclosure_fixture(tmp_path)
    expected = _enclosure_result(tmp_path, names)
    child_code = """
import json
import sys
from hashlib import sha256
from pathlib import Path
from acd.core.cad_normalize import normalize_3mf, normalize_stl, normalize_step
root = Path(sys.argv[1])
names = json.loads(sys.argv[2])
step = root / names["step"]
stl = root / names["stl"]
model = root / names["model"]
manifest = root / names["manifest"]
result = {
    "step": sha256(normalize_step(step.read_bytes())).hexdigest(),
    "model": sha256(normalize_3mf(model.read_bytes())).hexdigest(),
    "stl": sha256(normalize_stl(stl.read_bytes())).hexdigest(),
    "manifest": json.loads(manifest.read_text(encoding="utf-8")),
}
print(json.dumps(result, ensure_ascii=True, sort_keys=True))
"""
    completed = run_under_c_locale(child_code, tmp_path, Path(json.dumps(names)))
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == expected
