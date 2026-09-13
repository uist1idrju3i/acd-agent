from __future__ import annotations

import csv
import io
import struct
import zipfile
from pathlib import Path

import pytest

from acd.core.projection_format_check import (
    ProjectionFormatError,
    check_projection,
    check_projections,
)


def _write(path: Path, value: str | bytes) -> Path:
    if isinstance(value, str):
        path.write_text(value, encoding="utf-8")
    else:
        path.write_bytes(value)
    return path


def _zip_bytes(entries: dict[str, bytes]) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        for name, value in entries.items():
            archive.writestr(name, value)
    return stream.getvalue()


def _smf(*, header_length: int = 6, tracks: int = 1, balanced: bool = True) -> bytes:
    events = b"\x00\x90\x3c\x40"
    if balanced:
        events += b"\x00\x80\x3c\x40"
    events += b"\x00\xff\x2f\x00"
    track = b"MTrk" + struct.pack(">I", len(events)) + events
    return b"MThd" + struct.pack(">IHHH", header_length, 0, tracks, 96) + track


def test_check_projection_accepts_each_kind(tmp_path: Path) -> None:
    files: list[tuple[str, str, str | bytes]] = [
        ("board.kicad_pcb", "kicad_sexpr", '(kicad_pcb (general (thickness "1.6")))\n'),
        ("board.dsn", "dsn", "(pcb (parser (host version)))\n"),
        ("record.json", "json", '{"status": "ok"}\n'),
        ("table.csv", "csv", "a,b\n1,2\n\n"),
        (
            "archive.zip",
            "zip",
            _zip_bytes({"one.txt": b"one"}),
        ),
        (
            "board.gbr",
            "gerber",
            "%FSLAX46Y46*%\n%MOMM*%\n%ADD10C,0.2*%\nD10*\nM02*\n",
        ),
        ("board.drl", "excellon", "M48\nT01C0.3\n%\nX010Y020\nM30\n"),
        (
            "board.gbrjob",
            "gbrjob",
            '{"Header": {}, "FilesAttributes": [{"FileName": "F.Cu"}]}',
        ),
        ("song.mid", "smf", _smf()),
        (
            "part.step",
            "step",
            "ISO-10303-21;\nHEADER;\nENDSEC;\nDATA;\n#1=THING();\nENDSEC;\nEND-ISO-10303-21;\n",
        ),
        (
            "part.3mf",
            "threemf",
            _zip_bytes(
                {
                    "[Content_Types].xml": b"<Types />",
                    "3D/model.model": b"<model xmlns='urn:3mf:schema:core-2015' />",
                }
            ),
        ),
        (
            "part.stl",
            "stl",
            b"solid part\nendsolid part\n",
        ),
        ("drawing.svg", "svg", "<svg><g /></svg>"),
        ("notes.txt", "text", "UTF-8 text\n"),
    ]
    for filename, kind, value in files:
        path = _write(tmp_path / filename, value)
        record = check_projection(path, kind)  # type: ignore[arg-type]
        assert record["status"] == "ok"
        assert record["kind"] == kind
        assert record["byte_length"] == path.stat().st_size

    assert check_projection(tmp_path / "board.kicad_pcb", "kicad_sexpr")["root"] == "kicad_pcb"
    assert check_projection(tmp_path / "song.mid", "smf")["note_on_count"] == 1


def test_binary_stl_and_csv_summary(tmp_path: Path) -> None:
    triangle = bytes(50)
    stl = b" " * 80 + struct.pack("<I", 1) + triangle
    stl_record = check_projection(_write(tmp_path / "one.stl", stl), "stl")
    assert stl_record["encoding"] == "binary"
    assert stl_record["triangle_count"] == 1

    csv_path = tmp_path / "data.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as stream:
        csv.writer(stream).writerows([["a", "b"], ["1", "2"], ["3", "4"]])
    csv_record = check_projection(csv_path, "csv")
    assert csv_record["columns"] == 2
    assert csv_record["rows"] == 2


@pytest.mark.parametrize(
    ("kind", "value"),
    [
        ("gerber", "%FSLAX46Y46*%\n%MOMM*%\n%ADD10C,0.2*%\n"),
        ("excellon", "M48\nT01C0.3\n%\nX010Y020\n"),
        ("step", "ISO-10303-21;\nHEADER;\nENDSEC;\nDATA;\n"),
        ("csv", "a,b\n1\n"),
        ("svg", "<g />"),
        ("stl", b"solid\n"),
    ],
)
def test_broken_projection_is_rejected(
    tmp_path: Path, kind: str, value: str | bytes
) -> None:
    path = _write(tmp_path / "broken", value)
    with pytest.raises(ProjectionFormatError, match="broken"):
        check_projection(path, kind)  # type: ignore[arg-type]


def test_smf_failures_are_rejected(tmp_path: Path) -> None:
    for name, value in (
        ("header", _smf(header_length=7)),
        ("tracks", _smf(tracks=2)),
        ("unbalanced", _smf(balanced=False)),
    ):
        with pytest.raises(ProjectionFormatError):
            check_projection(_write(tmp_path / name, value), "smf")

    events = b"\x00\x90\x3c\x40"
    track = b"MTrk" + struct.pack(">I", len(events)) + events
    with pytest.raises(ProjectionFormatError, match="End of Track"):
        check_projection(
            _write(
                tmp_path / "no-eot",
                b"MThd" + struct.pack(">IHHH", 6, 0, 1, 96) + track,
            ),
            "smf",
        )


def test_threemf_and_zip_crc_failures_are_rejected(tmp_path: Path) -> None:
    with pytest.raises(ProjectionFormatError, match="model"):
        check_projection(
            _write(
                tmp_path / "missing-model.3mf",
                _zip_bytes({"[Content_Types].xml": b"<Types />"}),
            ),
            "threemf",
        )

    archive = bytearray(_zip_bytes({"one.txt": b"one"}))
    archive[archive.index(b"one")] ^= 0xFF
    with pytest.raises(ProjectionFormatError, match="CRC"):
        check_projection(_write(tmp_path / "corrupt.zip", bytes(archive)), "zip")


def test_check_projections_returns_sorted_records_and_fails_closed(tmp_path: Path) -> None:
    first = _write(tmp_path / "z.json", '{"ok": true}')
    second = _write(tmp_path / "a.json", "[]")
    checked = check_projections([(first, "json"), (second, "json")], root=tmp_path)
    assert list(checked) == ["a.json", "z.json"]
    assert checked["a.json"]["top_level_type"] == "array"

    broken = _write(tmp_path / "broken.json", "{")
    with pytest.raises(ProjectionFormatError):
        check_projections(
            [(first, "json"), (broken, "json"), (second, "json")],
            root=tmp_path,
        )
