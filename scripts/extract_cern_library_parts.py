#!/usr/bin/env python3
"""Extract the pinned CERN KiCad parts used by the ACD catalog."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import subprocess
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, cast


class ExtractionError(ValueError):
    """Raised when the pinned CERN source cannot be extracted safely."""


@dataclass(frozen=True)
class SExprNode:
    start: int
    end: int
    values: tuple[str, ...]
    children: tuple[SExprNode, ...]


@dataclass(frozen=True)
class SelectedPart:
    spec: dict[str, Any]
    row: dict[str, Any]
    symbol_library: str
    symbol_name: str
    footprint_library: str
    footprint_name: str


def _parse_string(text: str, position: int) -> tuple[str, int]:
    if text[position] != '"':
        raise ExtractionError("expected quoted s-expression string")
    position += 1
    value: list[str] = []
    while position < len(text):
        character = text[position]
        position += 1
        if character == '"':
            return "".join(value), position
        if character == "\\":
            if position >= len(text):
                raise ExtractionError("unterminated s-expression escape")
            value.append(text[position])
            position += 1
        else:
            value.append(character)
    raise ExtractionError("unterminated s-expression string")


def _parse_node(text: str, position: int) -> tuple[SExprNode, int]:
    while position < len(text) and text[position].isspace():
        position += 1
    if position >= len(text) or text[position] != "(":
        raise ExtractionError("expected s-expression list")
    start = position
    position += 1
    values: list[str] = []
    children: list[SExprNode] = []
    while True:
        while position < len(text) and text[position].isspace():
            position += 1
        if position >= len(text):
            raise ExtractionError("unterminated s-expression list")
        if text[position] == ")":
            return SExprNode(start, position + 1, tuple(values), tuple(children)), position + 1
        if text[position] == "(":
            child, position = _parse_node(text, position)
            children.append(child)
            continue
        if text[position] == '"':
            value, position = _parse_string(text, position)
        else:
            value_start = position
            while position < len(text) and text[position] not in "()\t\r\n ":
                position += 1
            value = text[value_start:position]
        values.append(value)


def _parse_library(path: Path) -> tuple[str, SExprNode]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ExtractionError(f"cannot read symbol library: {path}: {exc}") from exc
    root, position = _parse_node(text, 0)
    if text[position:].strip():
        raise ExtractionError(f"unexpected data after symbol library: {path}")
    if not root.values or root.values[0] != "kicad_symbol_lib":
        raise ExtractionError(f"invalid KiCad symbol library root: {path}")
    return text, root


def _direct_symbols(root: SExprNode) -> dict[str, SExprNode]:
    symbols: dict[str, SExprNode] = {}
    for child in root.children:
        if len(child.values) >= 2 and child.values[0] == "symbol":
            name = child.values[1]
            if name in symbols:
                raise ExtractionError(f"duplicate top-level symbol {name!r}")
            symbols[name] = child
    return symbols


def _extends(node: SExprNode) -> str | None:
    for child in node.children:
        if len(child.values) >= 2 and child.values[0] == "extends":
            return child.values[1]
    return None


def _sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _read_spec(path: Path) -> dict[str, Any]:
    try:
        raw_payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ExtractionError(f"invalid CERN parts spec: {path}: {exc}") from exc
    if not isinstance(raw_payload, dict):
        raise ExtractionError("CERN parts spec must be an object")
    payload = cast(dict[str, Any], raw_payload)
    if not isinstance(payload.get("parts"), list):
        raise ExtractionError("CERN parts spec must contain a parts list")
    for field in ("source_url", "source_commit", "retrieved_at", "license"):
        if not isinstance(payload.get(field), str) or not payload[field]:
            raise ExtractionError(f"CERN parts spec field is missing: {field}")
    return payload


def _source_head(source: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(source), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ExtractionError(f"cannot read source commit: {source}") from exc
    return result.stdout.strip()


def _read_checksums(source: Path) -> dict[str, str]:
    try:
        lines = (source / "CHECKSUMS").read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise ExtractionError(f"cannot read source CHECKSUMS: {exc}") from exc
    checksums: dict[str, str] = {}
    for line in lines:
        fields = line.split(maxsplit=1)
        if len(fields) == 2:
            checksums[fields[1]] = fields[0]
    return checksums


def _query_parts(source: Path, spec: dict[str, Any]) -> list[SelectedPart]:
    database = source / "CERN.sqlite"
    try:
        connection = sqlite3.connect(database)
        connection.row_factory = sqlite3.Row
    except sqlite3.Error as exc:
        raise ExtractionError(f"cannot open CERN database: {database}: {exc}") from exc
    selected: list[SelectedPart] = []
    try:
        for item in spec["parts"]:
            if not isinstance(item, dict):
                raise ExtractionError("every CERN spec part must be an object")
            item = cast(dict[str, Any], item)
            table = item.get("table")
            part_number = item.get("part_number")
            lib_symbol = item.get("lib_symbol")
            if not isinstance(table, str) or not table:
                raise ExtractionError("CERN spec part has invalid table")
            if not isinstance(part_number, str) or not part_number:
                raise ExtractionError("CERN spec part has invalid part_number")
            if not isinstance(lib_symbol, str) or not lib_symbol:
                raise ExtractionError("CERN spec part has invalid table/part_number/lib_symbol")
            quoted_table = '"' + table.replace('"', '""') + '"'
            try:
                rows = connection.execute(
                    f'SELECT * FROM {quoted_table} WHERE "Part Number"=? AND "LibSymbol"=?',
                    (part_number, lib_symbol),
                ).fetchall()
            except sqlite3.Error as exc:
                raise ExtractionError(f"cannot query CERN table {table!r}: {exc}") from exc
            if len(rows) != 1:
                raise ExtractionError(
                    f"CERN part mismatch for ({table}, {part_number}, {lib_symbol}): "
                    f"expected exactly one row, got {len(rows)}"
                )
            row = dict(rows[0])
            symbol_parts = lib_symbol.split(":", 1)
            footprint = row.get("LibFootprint")
            if len(symbol_parts) != 2 or not isinstance(footprint, str) or ":" not in footprint:
                raise ExtractionError(f"CERN row has invalid library mapping: {row}")
            footprint_parts = footprint.split(":", 1)
            selected.append(
                SelectedPart(
                    spec=item,
                    row=row,
                    symbol_library=symbol_parts[0],
                    symbol_name=symbol_parts[1],
                    footprint_library=footprint_parts[0],
                    footprint_name=footprint_parts[1],
                )
            )
    finally:
        connection.close()
    return selected


def _load_symbols(
    source: Path, selected: list[SelectedPart], checksums: dict[str, str]
) -> tuple[dict[str, str], tuple[str, ...]]:
    source_files = {part.symbol_library for part in selected}
    texts: dict[str, str] = {}
    symbols_by_library: dict[str, dict[str, SExprNode]] = {}
    headers: set[tuple[str, ...]] = set()
    for library in sorted(source_files):
        relative = f"SchLib/{library}.kicad_sym"
        path = source / relative
        if relative not in checksums:
            raise ExtractionError(f"missing CHECKSUMS entry: {relative}")
        text, root = _parse_library(path)
        symbols_by_library[library] = _direct_symbols(root)
        texts[library] = text
        header = tuple(
            line
            for line in text.splitlines()[:20]
            if line.lstrip().startswith(("(version ", "(generator ", "(generator_version "))
        )
        if len(header) != 3:
            raise ExtractionError(f"symbol library header is incomplete: {path}")
        headers.add(header)
    if len(headers) != 1:
        raise ExtractionError("selected CERN symbol libraries disagree on header")
    by_name: dict[str, str] = {}
    by_source: dict[str, str] = {}
    resolving: set[tuple[str, str]] = set()

    def collect(library: str, name: str) -> None:
        key = (library, name)
        if key in resolving:
            raise ExtractionError(f"cyclic CERN symbol extends chain: {library}:{name}")
        node = symbols_by_library.get(library, {}).get(name)
        if node is None:
            matches = [
                (candidate, values[name])
                for candidate, values in symbols_by_library.items()
                if name in values
            ]
            if len(matches) != 1:
                raise ExtractionError(f"missing CERN symbol {library}:{name}")
            library, node = matches[0]
        block = texts[library][node.start : node.end]
        previous = by_name.get(name)
        if previous is not None and previous != block and by_source[name] != library:
            raise ExtractionError(f"conflicting CERN symbol text for {name!r}")
        by_name[name] = block
        by_source[name] = library
        parent = _extends(node)
        if parent is not None:
            resolving.add(key)
            collect(library, parent)
            resolving.remove(key)

    for part in selected:
        collect(part.symbol_library, part.symbol_name)
    return by_name, next(iter(headers))


def _manifest_part(
    part: SelectedPart,
    symbol_source_md5: str,
    footprint_source_md5: str,
    footprint_sha256: str,
) -> dict[str, Any]:
    row = part.row
    return {
        "part_number": part.spec["part_number"],
        "table": part.spec["table"],
        "manufacturer": row.get("Manufacturer"),
        "manufacturer_part_number": row.get("Manufacturer Part Number"),
        "description": row.get("Part Description"),
        "status": row.get("Status"),
        "symbol": f"CERN:{part.symbol_name}",
        "symbol_source_lib": f"SchLib/{part.symbol_library}.kicad_sym",
        "symbol_source_md5": symbol_source_md5,
        "footprint": f"CERN:{part.footprint_name}",
        "footprint_source_lib": f"PcbLib/{part.footprint_library}.pretty",
        "footprint_source_md5": footprint_source_md5,
        "footprint_sha256": footprint_sha256,
    }


def _write_outputs(
    source: Path,
    spec: dict[str, Any],
    out_dir: Path,
    emit_catalog_entries: Path | None,
) -> None:
    checksums = _read_checksums(source)
    selected = _query_parts(source, spec)
    symbols, header = _load_symbols(source, selected, checksums)
    out_dir.mkdir(parents=True, exist_ok=True)
    pretty_dir = out_dir / "CERN.pretty"
    pretty_dir.mkdir(parents=True, exist_ok=True)
    for path in pretty_dir.glob("*.kicad_mod"):
        path.unlink()
    footprint_bytes: dict[str, bytes] = {}
    footprint_metadata: dict[str, tuple[str, str]] = {}
    for part in selected:
        relative = (
            f"PcbLib/{part.footprint_library}.pretty/{part.footprint_name}.kicad_mod"
        )
        path = source / relative
        if relative not in checksums or not path.is_file():
            raise ExtractionError(f"missing CERN footprint or CHECKSUMS entry: {relative}")
        data = path.read_bytes()
        previous = footprint_bytes.get(part.footprint_name)
        if previous is not None and previous != data:
            raise ExtractionError(f"conflicting CERN footprint text: {part.footprint_name}")
        footprint_bytes[part.footprint_name] = data
        footprint_metadata[part.footprint_name] = (relative, checksums[relative])
    for name, data in sorted(footprint_bytes.items()):
        (pretty_dir / f"{name}.kicad_mod").write_bytes(data)
    symbol_path = out_dir / "CERN.kicad_sym"
    symbol_blocks = [symbols[name].rstrip("\r\n") for name in sorted(symbols)]
    symbol_text = "\n".join(["(kicad_symbol_lib", *header, *symbol_blocks, ")"]) + "\n"
    symbol_path.write_text(symbol_text, encoding="utf-8", newline="\n")
    symbol_file_sha256 = _sha256(symbol_path.read_bytes())
    manifest_parts: list[dict[str, Any]] = []
    for part in selected:
        symbol_relative = f"SchLib/{part.symbol_library}.kicad_sym"
        _, footprint_md5 = footprint_metadata[part.footprint_name]
        manifest_parts.append(
            _manifest_part(
                part,
                checksums[symbol_relative],
                footprint_md5,
                _sha256(footprint_bytes[part.footprint_name]),
            )
        )
    manifest = {
        "source_url": spec["source_url"],
        "source_commit": spec["source_commit"],
        "license": spec["license"],
        "retrieved_at": spec["retrieved_at"],
        "parts": manifest_parts,
        "symbol_file_sha256": symbol_file_sha256,
    }
    (out_dir / "CERN.manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    license_source = source / "LICENSES" / "CERN-OHL-P-2.0.txt"
    license_target = out_dir / "LICENSES" / "CERN-OHL-P-2.0.txt"
    license_target.parent.mkdir(parents=True, exist_ok=True)
    license_target.write_bytes(license_source.read_bytes())
    if emit_catalog_entries is not None:
        emit_catalog_entries.mkdir(parents=True, exist_ok=True)
        for path in emit_catalog_entries.glob("*.json"):
            path.unlink()
        for part in selected:
            row = part.row
            entry = {
                "part_number": row.get("Manufacturer Part Number"),
                "kind": part.spec["kind"],
                "value": part.spec["value"],
                "package": part.footprint_name,
                "library_ref": {
                    "symbol": f"CERN:{part.symbol_name}",
                    "symbol_file": "libraries/CERN.kicad_sym",
                    "symbol_source": spec["source_url"],
                    "symbol_source_ref": spec["source_commit"],
                    "symbol_sha256": symbol_file_sha256,
                    "footprint": f"CERN:{part.footprint_name}",
                    "footprint_file": f"libraries/CERN.pretty/{part.footprint_name}.kicad_mod",
                    "footprint_source": spec["source_url"],
                    "footprint_source_ref": spec["source_commit"],
                    "footprint_sha256": _sha256(
                        (pretty_dir / f"{part.footprint_name}.kicad_mod").read_bytes()
                    ),
                },
            }
            filename = row.get("Manufacturer Part Number") or part.spec["part_number"]
            (emit_catalog_entries / f"{filename}.json").write_text(
                json.dumps(entry, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
                newline="\n",
            )


def _compare_check_outputs(out_dir: Path, expected_dir: Path) -> None:
    expected_files = {
        "CERN.kicad_sym",
        "CERN.manifest.json",
        *(
            f"CERN.pretty/{path.name}"
            for path in expected_dir.joinpath("CERN.pretty").glob("*.kicad_mod")
        ),
    }
    actual_files = {
        "CERN.kicad_sym",
        "CERN.manifest.json",
        *(
            f"CERN.pretty/{path.name}"
            for path in out_dir.joinpath("CERN.pretty").glob("*.kicad_mod")
        ),
    }
    if expected_files != actual_files:
        raise ExtractionError(
            "CERN extracted file set drift: "
            f"expected {sorted(expected_files)}, got {sorted(actual_files)}"
        )
    for relative in sorted(expected_files):
        expected = expected_dir / relative
        actual = out_dir / relative
        if expected.read_bytes() != actual.read_bytes():
            raise ExtractionError(f"CERN extracted file drift: {relative}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="upstream CERN checkout")
    parser.add_argument("--spec", type=Path, default=Path("libraries/CERN.parts.json"))
    parser.add_argument("--out-dir", type=Path, default=Path("libraries"))
    parser.add_argument("--check", action="store_true", help="check committed extraction for drift")
    parser.add_argument("--emit-catalog-entries", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        spec = _read_spec(args.spec)
        actual_commit = _source_head(args.source)
        if actual_commit != spec["source_commit"]:
            raise ExtractionError(
                "CERN source commit mismatch: "
                f"expected {spec['source_commit']}, got {actual_commit}"
            )
        if args.check:
            with TemporaryDirectory(prefix="cern-library-check-") as temporary:
                temporary_dir = Path(temporary)
                _write_outputs(args.source, spec, temporary_dir, None)
                _compare_check_outputs(args.out_dir, temporary_dir)
        else:
            _write_outputs(args.source, spec, args.out_dir, args.emit_catalog_entries)
        print(json.dumps({"ok": True, "check": args.check}, sort_keys=True))
        return 0
    except (ExtractionError, OSError, sqlite3.Error) as exc:
        print(
            json.dumps(
                {"ok": False, "fail_closed": True, "failure_reason": str(exc)},
                sort_keys=True,
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
