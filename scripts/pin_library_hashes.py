"""Compute and pin symbol/footprint sha256 declarations in a fixture spec.

The parts catalog and ``components[].attrs`` declare ``symbol_file`` /
``footprint_file`` paths whose ``*_sha256`` companions must match the file
bytes exactly. Writing those digests by hand means a failed container run per
component. This tool resolves each declared path through the single
library-asset contract, prints ``refdes  kind  file  declared  computed
state`` per asset with ``state`` in ``match|mismatch|unpinned|missing``, and
with ``--write`` rewrites the spec in place so every resolvable attrs-declared
asset carries its computed digest.

Container-absolute declarations (``/usr/share/kicad/…``) only exist inside the
digest-locked image: run this tool via ``scripts/run_in_workspace.py`` so the
``missing`` rows can be pinned. Library declarations and hash checks are left
untouched — the tool edits only the design input the agent already maintains.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from acd.core.library_assets import (
    LIBRARY_ASSET_ATTRS,
    LibraryAssetError,
    resolve_library_asset,
    sha256_of_asset,
)
from acd.core.part_selection import PartSelectionError, select_part
from acd.schema.parts_catalog import ComponentPartRequest


@dataclass(frozen=True)
class AssetRow:
    refdes: str
    kind: str
    declared_path: str
    declared: str
    computed: str
    state: str  # match | mismatch | unpinned | missing
    # The spec attrs dict this row's hash can be written back to; None when the
    # declaration is owned by the parts catalog (part_request components).
    write_attrs: dict[str, Any] | None
    hash_key: str | None


def _resolve(declared_path: str, library_root: Path | None) -> Path:
    if library_root is None:
        return resolve_library_asset(declared_path)
    path = Path(declared_path)
    if path.is_absolute():
        return path
    return (library_root / path).resolve()


def _asset_rows(
    component: dict[str, Any],
    library_root: Path | None,
) -> list[AssetRow]:
    rows: list[AssetRow] = []
    refdes = str(component.get("refdes", "?"))
    raw_attrs = component.get("attrs")
    attrs: dict[str, Any] = (
        cast(dict[str, Any], raw_attrs) if isinstance(raw_attrs, dict) else {}
    )
    raw_request = component.get("part_request")
    catalog_ref: dict[str, str] = {}
    if isinstance(raw_request, dict):
        request = ComponentPartRequest.model_validate(raw_request)
        catalog_ref = select_part(request).entry.library_ref.model_dump(
            mode="json"
        )
    for path_key, hash_key in LIBRARY_ASSET_ATTRS:
        declared_path: Any = attrs.get(path_key) or catalog_ref.get(path_key)
        if declared_path is None:
            continue
        write_attrs: dict[str, Any] | None = attrs if path_key in attrs else None
        declared = (
            str(attrs.get(hash_key))
            if path_key in attrs and attrs.get(hash_key) is not None
            else str(catalog_ref.get(hash_key, ""))
        )
        resolved = _resolve(str(declared_path), library_root)
        if not resolved.is_file():
            rows.append(
                AssetRow(
                    refdes,
                    path_key,
                    str(declared_path),
                    declared or "-",
                    "-",
                    "missing",
                    write_attrs,
                    hash_key,
                )
            )
            continue
        computed = sha256_of_asset(resolved)
        state = (
            "unpinned"
            if not declared
            else ("match" if declared == computed else "mismatch")
        )
        rows.append(
            AssetRow(
                refdes,
                path_key,
                str(declared_path),
                declared or "-",
                computed,
                state,
                write_attrs,
                hash_key,
            )
        )
    return rows


def _print_table(rows: list[AssetRow]) -> None:
    print(f"{'refdes'}\t{'kind'}\t{'file'}\t{'declared'}\t{'computed'}\t{'state'}")
    for row in rows:
        print(
            f"{row.refdes}\t{row.kind}\t{row.declared_path}\t"
            f"{row.declared}\t{row.computed}\t{row.state}"
        )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True, help="spec.json path")
    parser.add_argument(
        "--write",
        action="store_true",
        help="rewrite the spec in place with the computed sha256 values",
    )
    parser.add_argument(
        "--library-root",
        type=Path,
        default=None,
        help="resolve relative library declarations under this directory "
        "instead of the canonical libraries/ store",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        spec = json.loads(args.spec.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"spec is unreadable: {args.spec}: {exc}")
        return 1
    if not isinstance(spec, dict):
        print(f"spec is not an object: {args.spec}")
        return 1
    spec_dict = cast(dict[str, Any], spec)
    raw_components = spec_dict.get("components")
    components: list[dict[str, Any]] = (
        [
            cast(dict[str, Any], item)
            for item in cast(list[Any], raw_components)
            if isinstance(item, dict)
        ]
        if isinstance(raw_components, list)
        else []
    )
    try:
        rows = [
            row
            for component in components
            for row in _asset_rows(component, args.library_root)
        ]
    except (LibraryAssetError, PartSelectionError, ValueError) as exc:
        print(f"library pin could not be evaluated: {exc}")
        return 1
    if not rows:
        print(f"{args.spec}: no library declarations found")
        return 1
    _print_table(rows)
    missing = [row for row in rows if row.state == "missing"]
    if args.write:
        wrote = False
        for row in rows:
            if (
                row.write_attrs is not None
                and row.hash_key is not None
                and row.state in {"unpinned", "mismatch"}
            ):
                row.write_attrs[row.hash_key] = row.computed
                wrote = True
        if wrote:
            args.spec.write_text(
                json.dumps(spec_dict, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            print(f"wrote {args.spec}")
            rows = [
                row
                for component in components
                for row in _asset_rows(component, args.library_root)
            ]
            _print_table(rows)
    if missing:
        paths = sorted({row.declared_path for row in missing})
        print(
            "missing library files on this host: "
            + ", ".join(paths)
            + "; run inside the digest-locked container via "
            "scripts/run_in_workspace.py so /usr/share/kicad assets resolve"
        )
        return 1
    if any(row.state != "match" for row in rows):
        print(
            "unpinned or mismatched library declarations remain"
            + ("" if args.write else "; rerun with --write to pin them")
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
