#!/usr/bin/env python3
"""Select the KiCad 3D package models referenced by a PCB."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import cast

_MODEL_RE = re.compile(r'\(model\s+"([^"]+)"')
_KICAD_PACKAGE_RE = re.compile(
    r"(?:\$\{KICAD\d+_3DMODEL_DIR\}/)?([^/]+)\.3dshapes/(.+)"
)


def select_models(pcb_path: Path) -> dict[str, object]:
    text = pcb_path.read_text(encoding="utf-8")
    entries: set[tuple[str, str]] = set()
    for reference in _MODEL_RE.findall(text):
        match = _KICAD_PACKAGE_RE.fullmatch(reference)
        if match is None:
            continue
        footprint_lib, model_rel_path = match.groups()
        if model_rel_path.lower().endswith((".step", ".stp", ".wrl")):
            entries.add((footprint_lib, model_rel_path))
    return {
        "schema": "acd.kicad-3d-models/1",
        "entries": [
            {"footprint_lib": library, "model_rel_path": model}
            for library, model in sorted(entries)
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pcb", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        selected = select_models(args.pcb)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(selected, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"FAIL: {exc}")
        return 2
    entries = cast(list[dict[str, str]], selected["entries"])
    print(f"WROTE {args.out}: {len(entries)} models")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
