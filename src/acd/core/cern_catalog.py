"""Dynamic selection from the pinned CERN KiCad library database."""

from __future__ import annotations

import hashlib
import re
import sqlite3
import subprocess
from dataclasses import dataclass
from pathlib import Path

CERN_SOURCE_URL = "https://gitlab.com/ohwr/cern-kicad-libs"
CERN_CATALOG_ID = "cern-kicad-libs"
CERN_SUBMODULE = Path("libraries/cern-kicad-libs")


class CernCatalogError(ValueError):
    """Raised when the pinned CERN catalog cannot resolve a part."""


@dataclass(frozen=True)
class ResolvedCernPart:
    part_number: str
    symbol: str
    symbol_path: Path
    symbol_file: str
    symbol_sha256: str
    footprint: str
    footprint_path: Path
    footprint_file: str
    footprint_sha256: str


def pinned_cern_commit(root: Path) -> str:
    readme = root / "libraries" / "README.md"
    try:
        text = readme.read_text(encoding="utf-8")
    except OSError as exc:
        raise CernCatalogError(
            f"CERN source pin is missing: {readme}"
        ) from exc
    match = re.search(
        rf"- 取得元URL:\s*`{re.escape(CERN_SOURCE_URL)}`\s*"
        r"\n- 取得commit:\s*`([0-9a-f]{40})`",
        text,
    )
    if match is None:
        raise CernCatalogError("CERN source pin is missing from libraries/README.md")
    return match.group(1)


def cern_checkout_commit(root: Path) -> str:
    checkout = root / CERN_SUBMODULE
    try:
        result = subprocess.run(
            ["git", "-C", str(checkout), "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise CernCatalogError("CERN submodule is not initialized") from exc
    actual = result.stdout.strip()
    expected = pinned_cern_commit(root)
    if actual != expected:
        raise CernCatalogError(
            f"CERN submodule commit drift: expected {expected}, got {actual}"
        )
    return actual


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _split_library_ref(value: object, field: str) -> tuple[str, str]:
    if not isinstance(value, str) or not value:
        raise CernCatalogError(f"CERN {field} is empty")
    library, separator, name = value.partition(":")
    if not separator or not library or not name:
        raise CernCatalogError(f"CERN {field} is invalid: {value!r}")
    if Path(library).name != library or Path(name).name != name:
        raise CernCatalogError(f"CERN {field} is invalid: {value!r}")
    return library, name


def resolve_cern_part(root: Path, part_number: str) -> ResolvedCernPart:
    checkout = root / CERN_SUBMODULE
    database = checkout / "CERN.sqlite"
    if not database.is_file():
        raise CernCatalogError(f"CERN catalog database is missing: {database}")
    try:
        connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    except (OSError, sqlite3.Error) as exc:
        raise CernCatalogError(f"CERN catalog cannot be opened: {database}") from exc
    rows: list[tuple[str, str | None, str | None]] = []
    try:
        try:
            tables = [
                str(row[0])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            ]
            for table in tables:
                quoted_table = _quote_identifier(table)
                try:
                    matches = connection.execute(
                        f"SELECT {_quote_identifier('LibSymbol')}, "
                        f"{_quote_identifier('LibFootprint')} "
                        f"FROM {quoted_table} "
                        f"WHERE {_quote_identifier('Part Number')} = ?",
                        (part_number,),
                    ).fetchall()
                except sqlite3.Error as exc:
                    raise CernCatalogError(
                        f"CERN catalog table cannot be queried: {table}"
                    ) from exc
                rows.extend(
                    (table, row[0], row[1])
                    for row in matches
                )
        except sqlite3.Error as exc:
            raise CernCatalogError("CERN catalog cannot be queried") from exc
    finally:
        connection.close()
    if not rows:
        raise CernCatalogError(f"CERN catalog has no part {part_number!r}")
    tables_found = sorted({row[0] for row in rows})
    if len(tables_found) > 1:
        tables = ", ".join(tables_found)
        raise CernCatalogError(
            f"CERN catalog part {part_number!r} is ambiguous across tables: {tables}"
        )
    rows.sort(key=lambda row: (str(row[1]), str(row[2])))

    _, raw_symbol, raw_footprint = rows[0]
    symbol_library, _symbol_name = _split_library_ref(raw_symbol, "LibSymbol")
    footprint_library, footprint_name = _split_library_ref(
        raw_footprint, "LibFootprint"
    )
    symbol_path = checkout / "SchLib" / f"{symbol_library}.kicad_sym"
    footprint_path = (
        checkout
        / "PcbLib"
        / f"{footprint_library}.pretty"
        / f"{footprint_name}.kicad_mod"
    )
    if not symbol_path.is_file():
        raise CernCatalogError(f"CERN symbol file is missing: {symbol_path}")
    if not footprint_path.is_file():
        raise CernCatalogError(f"CERN footprint file is missing: {footprint_path}")
    return ResolvedCernPart(
        part_number=part_number,
        symbol=str(raw_symbol),
        symbol_path=symbol_path,
        symbol_file=str(
            CERN_SUBMODULE / "SchLib" / f"{symbol_library}.kicad_sym"
        ),
        symbol_sha256=_sha256(symbol_path),
        footprint=str(raw_footprint),
        footprint_path=footprint_path,
        footprint_file=str(
            CERN_SUBMODULE
            / "PcbLib"
            / f"{footprint_library}.pretty"
            / f"{footprint_name}.kicad_mod"
        ),
        footprint_sha256=_sha256(footprint_path),
    )


def cern_catalog_hash(root: Path) -> str:
    database = root / CERN_SUBMODULE / "CERN.sqlite"
    if not database.is_file():
        raise CernCatalogError(f"CERN catalog database is missing: {database}")
    return _sha256(database)


__all__ = [
    "CERN_CATALOG_ID",
    "CERN_SOURCE_URL",
    "CERN_SUBMODULE",
    "CernCatalogError",
    "ResolvedCernPart",
    "cern_catalog_hash",
    "cern_checkout_commit",
    "pinned_cern_commit",
    "resolve_cern_part",
]
