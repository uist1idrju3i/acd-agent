#!/usr/bin/env python3
"""Select the KiCad 3D package models referenced by a PCB.

References that match a declared ``missing_upstream`` item (a model the
footprint references but kicad-packages3d does not ship) are kept in the
``missing_upstream`` list instead of ``entries`` so the image bundler can
assert their absence rather than fail on a missing source file.
"""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import cast

_MODEL_RE = re.compile(r'\(model\s+"([^"]+)"')
_KICAD_PACKAGE_RE = re.compile(
    r"(?:\$\{KICAD\d+_3DMODEL_DIR\}/)?([^/]+)\.3dshapes/(.+)"
)
_SCHEMA = "acd.kicad-3d-models/2"


def select_models(
    pcb_path: Path, *, missing_upstream: Sequence[Mapping[str, str]] = ()
) -> dict[str, object]:
    declared: dict[tuple[str, str], str] = {}
    for item in missing_upstream:
        values = {key: item.get(key) for key in ("footprint_lib", "model_rel_path", "note")}
        if not all(isinstance(value, str) and value for value in values.values()):
            raise ValueError(
                "missing_upstream items need non-empty footprint_lib, "
                f"model_rel_path and note: {dict(item)!r}"
            )
        declared[(item["footprint_lib"], item["model_rel_path"])] = item["note"]

    text = pcb_path.read_text(encoding="utf-8")
    entries: set[tuple[str, str]] = set()
    missing: dict[tuple[str, str], str] = {}
    for reference in _MODEL_RE.findall(text):
        match = _KICAD_PACKAGE_RE.fullmatch(reference)
        if match is None:
            continue
        key = (match.group(1), match.group(2))
        if not key[1].lower().endswith((".step", ".stp", ".wrl")):
            continue
        if key in declared:
            missing[key] = declared[key]
        else:
            entries.add(key)
    return {
        "schema": _SCHEMA,
        "entries": [
            {"footprint_lib": library, "model_rel_path": model}
            for library, model in sorted(entries)
        ],
        "missing_upstream": [
            {
                "footprint_lib": library,
                "model_rel_path": model,
                "note": note,
            }
            for (library, model), note in sorted(missing.items())
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pcb", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        missing_upstream: Sequence[Mapping[str, str]] = []
        if args.out.exists():
            existing = json.loads(args.out.read_text(encoding="utf-8"))
            missing_upstream = existing.get("missing_upstream", [])
        selected = select_models(args.pcb, missing_upstream=missing_upstream)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(selected, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"FAIL: {exc}")
        return 2
    entries = cast(list[dict[str, str]], selected["entries"])
    missing_items = cast(list[dict[str, str]], selected["missing_upstream"])
    print(
        f"WROTE {args.out}: {len(entries)} models, "
        f"{len(missing_items)} missing_upstream"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
