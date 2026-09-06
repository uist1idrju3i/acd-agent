#!/usr/bin/env python3
"""Emit catalog entries directly from the pinned CERN submodule."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import subprocess
from pathlib import Path
from typing import Any, cast


class EmitError(ValueError):
    """Raised when the pinned CERN catalog source is invalid."""


REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SUBMODULE = REPOSITORY_ROOT / "libraries" / "cern-kicad-libs"
DEFAULT_SPEC = REPOSITORY_ROOT / "libraries" / "cern-catalog-parts.json"


def _sha256(path: Path) -> str:
    try:
        return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise EmitError(f"library file cannot be read: {path}: {exc}") from exc


def _source_head(source: Path) -> str:
    try:
        return subprocess.run(
            ["git", "-C", str(source), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise EmitError(f"CERN submodule HEAD cannot be read: {source}") from exc


def _read_spec(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EmitError(f"invalid CERN catalog spec: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise EmitError("CERN catalog spec must be an object")
    spec = cast(dict[str, Any], payload)
    for field in ("source_url", "source_commit"):
        if not isinstance(spec.get(field), str) or not spec[field]:
            raise EmitError(f"CERN catalog spec field is missing: {field}")
    parts = spec.get("parts")
    if not isinstance(parts, list) or not parts:
        raise EmitError("CERN catalog spec must contain a non-empty parts list")
    required = {"table", "part_number", "lib_symbol", "kind", "value"}
    for index, raw_part in enumerate(cast(list[Any], parts)):
        if not isinstance(raw_part, dict):
            raise EmitError(f"CERN catalog part {index} is malformed")
        part = cast(dict[str, Any], raw_part)
        if not required <= part.keys():
            raise EmitError(f"CERN catalog part {index} is malformed")
        if not all(isinstance(part[field], str) and part[field] for field in required):
            raise EmitError(f"CERN catalog part {index} has an invalid field")
    return spec


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _query_parts(source: Path, spec: dict[str, Any]) -> list[dict[str, Any]]:
    database = source / "CERN.sqlite"
    if not database.is_file():
        raise EmitError(f"CERN database is missing: {database}")
    selected: list[dict[str, Any]] = []
    try:
        connection = sqlite3.connect(database)
    except sqlite3.Error as exc:
        raise EmitError(f"CERN database cannot be opened: {database}: {exc}") from exc
    try:
        for raw_part in cast(list[Any], spec["parts"]):
            part = cast(dict[str, Any], raw_part)
            table = cast(str, part["table"])
            part_number = cast(str, part["part_number"])
            lib_symbol = cast(str, part["lib_symbol"])
            try:
                rows = connection.execute(
                    f"SELECT * FROM {_quote_identifier(table)} "
                    'WHERE "Part Number"=? AND LibSymbol=?',
                    (part_number, lib_symbol),
                ).fetchall()
            except sqlite3.Error as exc:
                raise EmitError(f"cannot query CERN table {table!r}: {exc}") from exc
            if len(rows) != 1:
                raise EmitError(
                    f"CERN part mismatch for ({table}, {part_number}, {lib_symbol}): "
                    f"expected exactly one row, got {len(rows)}"
                )
            columns = [item[1] for item in connection.execute(
                f"PRAGMA table_info({_quote_identifier(table)})"
            ).fetchall()]
            row = dict(zip(columns, rows[0], strict=True))
            database_symbol = row.get("LibSymbol")
            database_footprint = row.get("LibFootprint")
            if database_symbol != lib_symbol:
                raise EmitError(
                    f"CERN LibSymbol mismatch for ({table}, {part_number}): "
                    f"expected {lib_symbol!r}, got {database_symbol!r}"
                )
            if not isinstance(database_footprint, str) or database_footprint.count(":") != 1:
                raise EmitError(f"CERN row has invalid LibFootprint: {database_footprint!r}")
            selected.append({"spec": part, "row": row})
    finally:
        connection.close()
    return selected


def _asset_paths(source: Path, selected: list[dict[str, Any]]) -> list[dict[str, Any]]:
    symbol_paths: dict[str, Path] = {}
    output: list[dict[str, Any]] = []
    for item in selected:
        part = cast(dict[str, Any], item["spec"])
        row = cast(dict[str, Any], item["row"])
        lib_symbol = cast(str, row["LibSymbol"])
        symbol_library, symbol_name = lib_symbol.split(":", 1)
        lib_footprint = cast(str, row["LibFootprint"])
        footprint_library, footprint_name = lib_footprint.split(":", 1)
        symbol_path = source / "SchLib" / f"{symbol_library}.kicad_sym"
        footprint_path = (
            source / "PcbLib" / f"{footprint_library}.pretty" / f"{footprint_name}.kicad_mod"
        )
        if not symbol_path.is_file():
            raise EmitError(f"CERN symbol library is missing: {symbol_path}")
        if not footprint_path.is_file():
            raise EmitError(f"CERN footprint is missing: {footprint_path}")
        prior_path = symbol_paths.get(symbol_name)
        if prior_path is not None and prior_path != symbol_path:
            raise EmitError(
                f"ambiguous CERN symbol name across libraries: {symbol_name!r}"
            )
        symbol_paths[symbol_name] = symbol_path
        output.append(
            {
                "part": part,
                "row": row,
                "symbol": lib_symbol,
                "symbol_file": symbol_path,
                "footprint": lib_footprint,
                "footprint_file": footprint_path,
            }
        )
    return output


def _emit_entries(
    selected: list[dict[str, Any]], source_url: str, source_commit: str, output_dir: Path
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for existing in output_dir.glob("*.json"):
        existing.unlink()
    for item in selected:
        part = cast(dict[str, Any], item["part"])
        row = cast(dict[str, Any], item["row"])
        symbol = cast(str, item["symbol"])
        symbol_file = cast(Path, item["symbol_file"])
        footprint = cast(str, item["footprint"])
        footprint_file = cast(Path, item["footprint_file"])
        footprint_name = footprint.split(":", 1)[1]
        entry = {
            "part_number": row.get("Manufacturer Part Number"),
            "kind": part["kind"],
            "value": part["value"],
            "package": footprint_name,
            "library_ref": {
                "symbol": symbol,
                "symbol_file": symbol_file.relative_to(REPOSITORY_ROOT).as_posix(),
                "symbol_source": source_url,
                "symbol_source_ref": source_commit,
                "symbol_sha256": _sha256(symbol_file),
                "footprint": footprint,
                "footprint_file": footprint_file.relative_to(REPOSITORY_ROOT).as_posix(),
                "footprint_source": source_url,
                "footprint_source_ref": source_commit,
                "footprint_sha256": _sha256(footprint_file),
            },
        }
        part_number = entry["part_number"]
        if not isinstance(part_number, str) or not part_number:
            raise EmitError(f"CERN row has no Manufacturer Part Number: {row}")
        (output_dir / f"{part_number}.json").write_text(
            json.dumps(entry, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, default=DEFAULT_SPEC)
    parser.add_argument("--submodule", type=Path, default=DEFAULT_SUBMODULE)
    parser.add_argument("--emit-catalog-entries", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        spec = _read_spec(args.spec.resolve())
        expected_commit = cast(str, spec["source_commit"])
        submodule = args.submodule.resolve()
        actual_commit = _source_head(submodule)
        if actual_commit != expected_commit:
            raise EmitError(
                f"CERN submodule commit mismatch: expected {expected_commit}, got {actual_commit}"
            )
        selected = _query_parts(submodule, spec)
        assets = _asset_paths(submodule, selected)
        _emit_entries(
            assets,
            cast(str, spec["source_url"]),
            expected_commit,
            args.emit_catalog_entries.resolve(),
        )
        print(json.dumps({"ok": True, "entries": len(assets)}, sort_keys=True))
        return 0
    except (EmitError, OSError, sqlite3.Error) as exc:
        print(json.dumps({"fail_closed": True, "ok": False, "failure_reason": str(exc)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
