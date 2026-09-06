"""Inventory GD1 references in executable and CI assets and detect drift.

GD1 (``golden-design-1``) stays the regression positive control, so the goal
is not zero references but a declared purpose for every reference that could
make GD1 a hidden prerequisite for another design.  ``contracts/
gd1-reference-inventory.json`` lists each file that mentions GD1 together with
its purpose and the number of referencing lines.  ``--check`` fails closed when
a file mentions GD1 without an inventory entry, when an inventory entry no
longer matches the source, or when the reference count changed, so that a new
GD1 default or branch surfaces as drift instead of silently becoming the only
path that works.  This report is an L3 observation and grants no pass authority.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Literal

from pydantic import Field

from acd.schema.common import AcdModel, NonEmptyStr

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INVENTORY = REPO_ROOT / "contracts" / "gd1-reference-inventory.json"
REFERENCE_PATTERN = re.compile(r"gd1|golden-design-1", re.IGNORECASE)
SCAN_ROOTS: tuple[str, ...] = (
    "src/acd",
    "scripts",
    "plugins/acd/hooks",
    "plugins/acd/commands",
    ".github/workflows",
)
SCAN_SUFFIXES = frozenset({".py", ".json", ".md", ".yml", ".yaml"})
EXCLUDED_PARTS = frozenset({"tests", "__pycache__"})

ReferencePurpose = Literal[
    "positive_control",
    "compatibility_alias",
    "default_fallback",
    "module_name",
    "message_text",
]


class GD1ReferenceEntry(AcdModel):
    path: NonEmptyStr
    purpose: ReferencePurpose
    reference_lines: int = Field(ge=1)
    note: NonEmptyStr


class GD1ReferenceInventory(AcdModel):
    schema_version: Literal["1.0"] = "1.0"
    record_class: Literal["L3"] = "L3"
    pass_evidence: Literal[False] = False
    scan_roots: list[str]
    entries: list[GD1ReferenceEntry]


class GD1ReferenceReport(AcdModel):
    record_class: Literal["L3"] = "L3"
    pass_evidence: Literal[False] = False
    status: Literal["pass", "fail"]
    inventory: NonEmptyStr
    scanned_files: int
    referencing_files: int
    default_fallback_files: list[str]
    undeclared: list[str]
    stale: list[str]
    count_drift: list[str]


def _candidate_files(root: Path, scan_roots: tuple[str, ...]) -> list[Path]:
    files: list[Path] = []
    for scan_root in scan_roots:
        base = root / scan_root
        if not base.exists():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file() or path.suffix not in SCAN_SUFFIXES:
                continue
            if EXCLUDED_PARTS & set(path.relative_to(root).parts):
                continue
            if path.name == "verify_gd1_references.py":
                continue
            files.append(path)
    return files


def scan_references(root: Path, scan_roots: tuple[str, ...]) -> tuple[int, dict[str, int]]:
    """Return the scanned file count and referencing-line counts by path."""
    counts: dict[str, int] = {}
    files = _candidate_files(root, scan_roots)
    for path in files:
        text = path.read_text(encoding="utf-8")
        lines = sum(1 for line in text.splitlines() if REFERENCE_PATTERN.search(line))
        if lines:
            counts[path.relative_to(root).as_posix()] = lines
    return len(files), counts


def load_inventory(path: Path) -> GD1ReferenceInventory:
    return GD1ReferenceInventory.model_validate_json(path.read_text(encoding="utf-8"))


def build_report(root: Path, inventory_path: Path) -> GD1ReferenceReport:
    inventory = load_inventory(inventory_path)
    scanned, counts = scan_references(root, tuple(inventory.scan_roots))
    declared = {entry.path: entry for entry in inventory.entries}
    undeclared = sorted(path for path in counts if path not in declared)
    stale = sorted(path for path in declared if path not in counts)
    count_drift = sorted(
        f"{path}: declared {declared[path].reference_lines}, found {found}"
        for path, found in counts.items()
        if path in declared and declared[path].reference_lines != found
    )
    duplicates = len(declared) != len(inventory.entries)
    status: Literal["pass", "fail"] = (
        "fail" if undeclared or stale or count_drift or duplicates else "pass"
    )
    return GD1ReferenceReport(
        status=status,
        inventory=inventory_path.relative_to(root).as_posix()
        if inventory_path.is_relative_to(root)
        else str(inventory_path),
        scanned_files=scanned,
        referencing_files=len(counts),
        default_fallback_files=sorted(
            entry.path for entry in inventory.entries if entry.purpose == "default_fallback"
        ),
        undeclared=undeclared,
        stale=stale,
        count_drift=count_drift,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail on inventory drift")
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    parser.add_argument(
        "--scan",
        action="store_true",
        help="print the current reference counts by file instead of the drift report",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    root = args.root.resolve()
    if args.scan:
        scanned, counts = scan_references(root, SCAN_ROOTS)
        print(json.dumps({"scanned_files": scanned, "references": counts}, indent=2))
        return 0
    try:
        report = build_report(root, args.inventory.resolve())
    except (OSError, ValueError) as exc:
        print(f"ERROR: GD1 reference inventory is unreadable: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report.model_dump(mode="json"), indent=2, ensure_ascii=False))
    if args.check and report.status != "pass":
        print("ERROR: GD1 reference inventory drift detected", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
