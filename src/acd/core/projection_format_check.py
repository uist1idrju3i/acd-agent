"""Independent byte-level readers for generated projection formats."""

from __future__ import annotations

import csv
import io
import json
import re
import struct
import xml.etree.ElementTree as ET
import zipfile
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Literal, cast

ProjectionKind = Literal[
    "kicad_sexpr",
    "dsn",
    "json",
    "csv",
    "zip",
    "gerber",
    "excellon",
    "gbrjob",
    "smf",
    "step",
    "threemf",
    "stl",
    "svg",
    "text",
]

CHECKER_NAME = "acd.core.projection_format_check"
CHECKER_VERSION = "1"


class ProjectionFormatError(ValueError):
    """A generated projection failed its independent format check."""

    def __init__(self, path: Path, reason: str) -> None:
        self.path = path
        self.reason = reason
        super().__init__(f"{path}: {reason}")


def _text(path: Path, data: bytes) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ProjectionFormatError(path, f"UTF-8 decode failed: {exc}") from exc


def _balanced_parentheses(path: Path, value: str) -> int:
    depth = 0
    maximum = 0
    quoted = False
    escaped = False
    for character in value:
        if quoted:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                quoted = False
            continue
        if character == '"':
            quoted = True
        elif character == "(":
            depth += 1
            maximum = max(maximum, depth)
        elif character == ")":
            depth -= 1
            if depth < 0:
                raise ProjectionFormatError(path, "parentheses close before they open")
    if quoted:
        raise ProjectionFormatError(path, "unterminated quoted string")
    if depth:
        raise ProjectionFormatError(path, "parentheses are not balanced")
    return maximum


def _read_json(path: Path, data: bytes) -> object:
    try:
        return json.loads(_text(path, data))
    except json.JSONDecodeError as exc:
        raise ProjectionFormatError(path, f"JSON parse failed: {exc}") from exc


def _check_kicad_sexpr(path: Path, data: bytes) -> dict[str, object]:
    value = _text(path, data).lstrip()
    if not value.startswith("(kicad_"):
        raise ProjectionFormatError(path, "root does not start with (kicad_")
    depth = _balanced_parentheses(path, value)
    root = value[1:].split(None, 1)[0].rstrip(")")
    return {"root": root, "depth_max": depth}


def _check_dsn(path: Path, data: bytes) -> dict[str, object]:
    value = _text(path, data).lstrip()
    if not value.startswith("(pcb"):
        raise ProjectionFormatError(path, "DSN root does not start with (pcb")
    _balanced_parentheses(path, value)
    return {"root": "pcb"}


def _check_json(path: Path, data: bytes) -> dict[str, object]:
    value = _read_json(path, data)
    if isinstance(value, dict):
        top_level_type = "object"
    elif isinstance(value, list):
        top_level_type = "array"
    elif value is None:
        top_level_type = "null"
    elif isinstance(value, bool):
        top_level_type = "boolean"
    elif isinstance(value, (int, float)):
        top_level_type = "number"
    else:
        top_level_type = "string"
    return {"top_level_type": top_level_type}


def _check_gbrjob(path: Path, data: bytes) -> dict[str, object]:
    value = _read_json(path, data)
    if not isinstance(value, dict):
        raise ProjectionFormatError(path, "gbrjob top level must be an object")
    record = cast(dict[str, object], value)
    if "Header" not in record or "FilesAttributes" not in record:
        raise ProjectionFormatError(path, "gbrjob requires Header and FilesAttributes")
    files_value = record["FilesAttributes"]
    if not isinstance(files_value, list):
        raise ProjectionFormatError(path, "gbrjob FilesAttributes must be a list")
    files = cast(list[object], files_value)
    return {"file_count": len(files)}


def _check_csv(path: Path, data: bytes) -> dict[str, object]:
    value = _text(path, data)
    rows = list(csv.reader(io.StringIO(value)))
    while rows and not rows[-1]:
        rows.pop()
    if not rows:
        raise ProjectionFormatError(path, "CSV has no header row")
    columns = len(rows[0])
    for index, row in enumerate(rows[1:], start=2):
        if len(row) != columns:
            raise ProjectionFormatError(
                path,
                f"CSV row {index} has {len(row)} columns; expected {columns}",
            )
    return {"columns": columns, "rows": len(rows) - 1}


def _check_zip(path: Path, data: bytes) -> dict[str, object]:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            bad_entry = archive.testzip()
            if bad_entry is not None:
                raise ProjectionFormatError(path, f"ZIP CRC check failed for {bad_entry}")
            return {"entry_count": len(archive.infolist())}
    except ProjectionFormatError:
        raise
    except (OSError, zipfile.BadZipFile) as exc:
        raise ProjectionFormatError(path, f"ZIP parse failed: {exc}") from exc


def _check_gerber(path: Path, data: bytes) -> dict[str, object]:
    value = _text(path, data)
    if "%FSLA" not in value:
        raise ProjectionFormatError(path, "Gerber format specification %FSLA is missing")
    unit_match = next(
        (unit for unit in ("MM", "IN") if f"%MO{unit}*%" in value),
        None,
    )
    if unit_match is None:
        raise ProjectionFormatError(path, "Gerber unit declaration is missing")
    apertures = sum(1 for line in value.splitlines() if line.startswith("%ADD"))
    if apertures == 0:
        raise ProjectionFormatError(path, "Gerber aperture declaration is missing")
    nonempty = [line.strip() for line in value.splitlines() if line.strip()]
    if not nonempty or nonempty[-1] != "M02*":
        raise ProjectionFormatError(path, "Gerber M02* terminator is missing")
    return {"apertures": apertures, "unit": unit_match}


def _check_excellon(path: Path, data: bytes) -> dict[str, object]:
    lines = [
        line.strip()
        for line in _text(path, data).splitlines()
        if line.strip() and not line.strip().startswith(";")
    ]
    if not lines or lines[0] != "M48":
        raise ProjectionFormatError(path, "Excellon M48 header is missing")
    try:
        header_end = next(
            index
            for index, line in enumerate(lines[1:], start=1)
            if line in {"%", "M95"}
        )
    except StopIteration as exc:
        raise ProjectionFormatError(path, "Excellon header terminator is missing") from exc
    tools = sum(
        1 for line in lines[1:header_end] if re.match(r"^T\d+C", line) is not None
    )
    if lines[-1] != "M30":
        raise ProjectionFormatError(path, "Excellon M30 terminator is missing")
    hits = sum(1 for line in lines[header_end + 1 : -1] if _is_excellon_hit(line))
    return {"tools": tools, "hits": hits}


def _is_excellon_hit(line: str) -> bool:
    return re.match(r"^X-?\d.*Y-?\d", line) is not None


def _read_vlq(path: Path, data: bytes, offset: int, end: int) -> tuple[int, int]:
    value = 0
    for _ in range(4):
        if offset >= end:
            raise ProjectionFormatError(path, "SMF variable-length value is truncated")
        byte = data[offset]
        offset += 1
        value = (value << 7) | (byte & 0x7F)
        if not byte & 0x80:
            return value, offset
    raise ProjectionFormatError(path, "SMF variable-length value is too long")


def _check_smf(path: Path, data: bytes) -> dict[str, object]:
    if len(data) < 14 or data[:4] != b"MThd":
        raise ProjectionFormatError(path, "SMF MThd header is missing")
    header_length = struct.unpack(">I", data[4:8])[0]
    if header_length != 6:
        raise ProjectionFormatError(path, "SMF MThd header length must be 6")
    format_type, track_count, division = struct.unpack(">HHH", data[8:14])
    if format_type not in {0, 1, 2}:
        raise ProjectionFormatError(path, f"SMF format {format_type} is unsupported")
    offset = 14
    note_on_count = 0
    note_balance: dict[tuple[int, int], int] = {}
    actual_tracks = 0
    while offset < len(data):
        if offset + 8 > len(data) or data[offset : offset + 4] != b"MTrk":
            raise ProjectionFormatError(path, "SMF track chunk is missing or malformed")
        length = struct.unpack(">I", data[offset + 4 : offset + 8])[0]
        track_start = offset + 8
        track_end = track_start + length
        if track_end > len(data):
            raise ProjectionFormatError(path, "SMF track chunk exceeds file length")
        actual_tracks += 1
        running_status: int | None = None
        cursor = track_start
        last_event_eot = False
        while cursor < track_end:
            _, cursor = _read_vlq(path, data, cursor, track_end)
            if cursor >= track_end:
                raise ProjectionFormatError(path, "SMF event status is missing")
            status = data[cursor]
            if status < 0x80:
                if running_status is None:
                    raise ProjectionFormatError(path, "SMF running status is missing")
                status = running_status
            else:
                cursor += 1
                if 0x80 <= status <= 0xEF:
                    running_status = status
                elif status not in {0xF0, 0xF7, 0xFF}:
                    running_status = None
            last_event_eot = False
            if status == 0xFF:
                if cursor >= track_end:
                    raise ProjectionFormatError(path, "SMF meta event type is missing")
                meta_type = data[cursor]
                cursor += 1
                length_value, cursor = _read_vlq(path, data, cursor, track_end)
                if cursor + length_value > track_end:
                    raise ProjectionFormatError(path, "SMF meta event exceeds track length")
                cursor += length_value
                last_event_eot = meta_type == 0x2F and length_value == 0
            elif status in {0xF0, 0xF7}:
                length_value, cursor = _read_vlq(path, data, cursor, track_end)
                if cursor + length_value > track_end:
                    raise ProjectionFormatError(path, "SMF sysex event exceeds track length")
                cursor += length_value
            elif 0x80 <= status <= 0xEF:
                message_type = status >> 4
                data_length = 1 if message_type in {0xC, 0xD} else 2
                if cursor + data_length > track_end:
                    raise ProjectionFormatError(path, "SMF channel event is truncated")
                first = data[cursor]
                second = data[cursor + 1] if data_length == 2 else 0
                cursor += data_length
                channel = status & 0x0F
                if message_type == 0x9 and second > 0:
                    note_on_count += 1
                    key = (channel, first)
                    note_balance[key] = note_balance.get(key, 0) + 1
                elif message_type == 0x8 or (message_type == 0x9 and second == 0):
                    key = (channel, first)
                    remaining = note_balance.get(key, 0) - 1
                    if remaining < 0:
                        raise ProjectionFormatError(path, "SMF note-off has no matching note-on")
                    if remaining:
                        note_balance[key] = remaining
                    else:
                        note_balance.pop(key, None)
            else:
                raise ProjectionFormatError(path, "SMF unsupported event status")
        if not last_event_eot:
            raise ProjectionFormatError(path, "SMF track lacks a final End of Track event")
        offset = track_end
    if actual_tracks != track_count:
        raise ProjectionFormatError(
            path,
            f"SMF header declares {track_count} tracks but found {actual_tracks}",
        )
    if note_balance:
        raise ProjectionFormatError(path, "SMF note-on and note-off events are unbalanced")
    return {
        "format": format_type,
        "tracks": actual_tracks,
        "division": division,
        "note_on_count": note_on_count,
        "notes_balanced": True,
    }


def _check_step(path: Path, data: bytes) -> dict[str, object]:
    value = _text(path, data)
    if not value.startswith("ISO-10303-21;"):
        raise ProjectionFormatError(path, "STEP header is missing")
    for marker in ("HEADER;", "ENDSEC;", "DATA;"):
        if marker not in value:
            raise ProjectionFormatError(path, f"STEP {marker} marker is missing")
    if not value.rstrip().endswith("END-ISO-10303-21;"):
        raise ProjectionFormatError(path, "STEP footer is missing")
    return {"entity_count": sum(1 for line in value.splitlines() if line.startswith("#"))}


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _check_threemf(path: Path, data: bytes) -> dict[str, object]:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            bad_entry = archive.testzip()
            if bad_entry is not None:
                raise ProjectionFormatError(path, f"3MF ZIP CRC check failed for {bad_entry}")
            names = archive.namelist()
            if "[Content_Types].xml" not in names:
                raise ProjectionFormatError(path, "3MF content types entry is missing")
            model_entries = [
                name for name in names if name.startswith("3D/") and name.endswith(".model")
            ]
            if not model_entries:
                raise ProjectionFormatError(path, "3MF model entry is missing")
            try:
                root = ET.fromstring(archive.read(model_entries[0]))
            except (ET.ParseError, KeyError) as exc:
                raise ProjectionFormatError(path, f"3MF model XML is invalid: {exc}") from exc
            if _local_name(root.tag) != "model":
                raise ProjectionFormatError(path, "3MF model XML root is not model")
            return {"entry_count": len(names), "model_entry": model_entries[0]}
    except ProjectionFormatError:
        raise
    except (OSError, zipfile.BadZipFile) as exc:
        raise ProjectionFormatError(path, f"3MF ZIP parse failed: {exc}") from exc


def _check_stl(path: Path, data: bytes) -> dict[str, object]:
    if len(data) >= 84:
        triangle_count = struct.unpack("<I", data[80:84])[0]
        if len(data) == 84 + triangle_count * 50:
            return {"encoding": "binary", "triangle_count": triangle_count}
    try:
        value = data.decode("utf-8")
    except UnicodeDecodeError:
        value = ""
    nonempty_lines = [line.strip() for line in value.splitlines() if line.strip()]
    if (
        nonempty_lines
        and nonempty_lines[0].startswith("solid")
        and nonempty_lines[-1].startswith("endsolid")
    ):
        return {
            "encoding": "ascii",
            "triangle_count": sum(
                1
                for line in value.splitlines()
                if line.strip().startswith("facet normal")
            ),
        }
    raise ProjectionFormatError(path, "STL is neither a valid binary nor ASCII document")


def _check_svg(path: Path, data: bytes) -> dict[str, object]:
    try:
        root = ET.fromstring(_text(path, data))
    except ET.ParseError as exc:
        raise ProjectionFormatError(path, f"SVG XML is invalid: {exc}") from exc
    if _local_name(root.tag) != "svg":
        raise ProjectionFormatError(path, "SVG root is not svg")
    return {"element_count": sum(1 for _ in root.iter())}


def check_projection(path: Path, kind: ProjectionKind) -> dict[str, object]:
    """Read one generated projection independently and return its check record."""
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ProjectionFormatError(path, f"file is unavailable: {exc}") from exc
    checks: dict[str, Callable[[Path, bytes], dict[str, object]]] = {
        "kicad_sexpr": _check_kicad_sexpr,
        "dsn": _check_dsn,
        "json": _check_json,
        "csv": _check_csv,
        "zip": _check_zip,
        "gerber": _check_gerber,
        "excellon": _check_excellon,
        "gbrjob": _check_gbrjob,
        "smf": _check_smf,
        "step": _check_step,
        "threemf": _check_threemf,
        "stl": _check_stl,
        "svg": _check_svg,
    }
    if kind == "text":
        _text(path, data)
        summary = {"unchecked_structure": True}
    elif kind not in checks:
        raise ProjectionFormatError(path, f"unsupported projection kind: {kind}")
    else:
        summary = checks[kind](path, data)
    return {
        "checker": CHECKER_NAME,
        "checker_version": CHECKER_VERSION,
        "kind": kind,
        "status": "ok",
        "byte_length": len(data),
        **summary,
    }


def check_projections(
    items: Sequence[tuple[Path, ProjectionKind]], *, root: Path
) -> dict[str, dict[str, object]]:
    """Check all projections and return a sorted, non-partial result mapping."""
    results: dict[str, dict[str, object]] = {}
    for path, kind in items:
        try:
            relative = str(path.relative_to(root))
        except ValueError as exc:
            raise ProjectionFormatError(path, f"path is outside root {root}") from exc
        results[relative] = check_projection(path, kind)
    return {key: results[key] for key in sorted(results)}


__all__ = [
    "CHECKER_NAME",
    "CHECKER_VERSION",
    "ProjectionFormatError",
    "ProjectionKind",
    "check_projection",
    "check_projections",
]
