"""Independent format check for the fixed-run projection package (fix18).

Each file is parsed by a reader that is independent from the writer that
produced it. Results are printed as `status<TAB>checker<TAB>path`.
"""

from __future__ import annotations

import csv
import json
import struct
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

ROOT = Path(sys.argv[1])
GERBER_EXT = {"gbr", "gtl", "gbl", "gts", "gbs", "gto", "gbo", "gtp", "gbp", "gko", "gm1"}


def check_midi(path: Path) -> str:
    import mido  # independent SMF reader

    data = path.read_bytes()
    assert data[:4] == b"MThd", "MThd missing"
    _, ntrk, _ = struct.unpack(">HHH", data[8:14])
    mf = mido.MidiFile(path)
    assert len(mf.tracks) == ntrk, f"track count {len(mf.tracks)} != header {ntrk}"
    ons = sum(1 for t in mf.tracks for m in t if m.type == "note_on" and m.velocity > 0)
    offs = sum(
        1
        for t in mf.tracks
        for m in t
        if m.type == "note_off" or (m.type == "note_on" and m.velocity == 0)
    )
    assert ons == offs and ons > 0, f"note_on {ons} vs note_off {offs}"
    csv_out = subprocess.run(["midicsv", str(path)], capture_output=True, text=True, check=True)
    assert "End_track" in csv_out.stdout
    return f"mido+midicsv tracks={ntrk} notes={ons} length={mf.length:.1f}s"


def check_3mf(path: Path) -> str:
    with zipfile.ZipFile(path) as z:
        assert z.testzip() is None, "zip CRC failure"
        models = [n for n in z.namelist() if n.endswith(".model")]
        assert models, "no 3D/*.model"
        root = ET.fromstring(z.read(models[0]))
        objects = root.findall(".//{*}object")
        assert objects, "no <object>"
    return f"zipfile+ElementTree objects={len(objects)}"


def check_step(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("ISO-10303-21;"), "header"
    assert text.rstrip().endswith("END-ISO-10303-21;"), "footer"
    assert "ENDSEC;" in text and "DATA;" in text, "sections"
    return f"ISO-10303-21 entities={sum(1 for line in text.splitlines() if line.startswith('#'))}"


def check_gerber(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    assert "%FSLA" in text and "%MO" in text, "format/unit spec"
    assert text.rstrip().endswith("M02*"), "M02 terminator"
    return f"RS-274X ops={text.count('D01*') + text.count('D03*')}"


def check_drill(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("M48"), "M48 header"
    assert text.rstrip().endswith("M30"), "M30 terminator"
    return f"Excellon holes={sum(1 for line in text.splitlines() if line.startswith('X'))}"


def check_json(path: Path) -> str:
    json.loads(path.read_text(encoding="utf-8"))
    return "json"


def check_svg(path: Path) -> str:
    root = ET.parse(path).getroot()
    assert root.tag.endswith("svg"), root.tag
    return "ElementTree svg"


def check_csv(path: Path) -> str:
    rows = list(csv.reader(path.read_text(encoding="utf-8").splitlines()))
    assert len(rows) > 1 and all(len(r) == len(rows[0]) for r in rows), "ragged rows"
    return f"csv rows={len(rows) - 1}"


def check_text(path: Path) -> str:
    path.read_text(encoding="utf-8")
    return "utf-8 text"


CHECKERS = {
    "mid": check_midi,
    "3mf": check_3mf,
    "step": check_step,
    "drl": check_drill,
    "json": check_json,
    "gbrjob": check_json,
    "svg": check_svg,
    "csv": check_csv,
    "md": check_text,
    "diff": check_text,
    "txt": check_text,
    "py": check_text,
    "log": check_text,
}
REPORT_NAME = "projection-format-check.txt"

failed = 0
for path in sorted(p for p in ROOT.rglob("*") if p.is_file() and p.name != REPORT_NAME):
    ext = path.suffix.lstrip(".").lower()
    checker = check_gerber if ext in GERBER_EXT else CHECKERS.get(ext)
    rel = path.relative_to(ROOT)
    if checker is None:
        print(f"UNCHECKED\t-\t{rel}")
        failed += 1
        continue
    try:
        print(f"OK\t{checker(path)}\t{rel}")
    except Exception as exc:
        print(f"FAIL\t{exc!r}\t{rel}")
        failed += 1
checked = sum(1 for p in ROOT.rglob("*") if p.is_file() and p.name != REPORT_NAME)
print(f"# files={checked} failed_or_unchecked={failed}")
sys.exit(1 if failed else 0)
