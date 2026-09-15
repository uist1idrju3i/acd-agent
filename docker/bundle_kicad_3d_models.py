#!/usr/bin/env python3
"""Bundle the allowlisted KiCad 3D package models into the tools image.

Copies each ``entries`` model from the installed ``kicad-packages3d`` tree to the
destination and fails closed when a source file is missing. Each
``missing_upstream`` item declares a model the footprint references but the
package does not ship; the bundler asserts its absence so an upstream addition
fails the build and forces reclassification into ``entries``.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any

_SCHEMA = "acd.kicad-3d-models/2"


def _fail(message: str) -> int:
    print(f"FAIL: {message}")
    return 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, default=Path("/usr/share/kicad/3dmodels"))
    parser.add_argument("--dest", type=Path, default=Path("/opt/acd/kicad-3d"))
    args = parser.parse_args(argv)

    manifest: dict[str, Any] = json.loads(args.manifest.read_text(encoding="utf-8"))
    if manifest.get("schema") != _SCHEMA:
        return _fail(f"unsupported schema {manifest.get('schema')!r}; expected {_SCHEMA!r}")

    bundled = 0
    for item in manifest.get("entries", []):
        rel = Path(item["footprint_lib"] + ".3dshapes") / item["model_rel_path"]
        source = args.source_root / rel
        if not source.is_file():
            return _fail(f"{source} is not shipped by kicad-packages3d")
        target = args.dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        bundled += 1

    missing = 0
    for item in manifest.get("missing_upstream", []):
        rel = Path(item["footprint_lib"] + ".3dshapes") / item["model_rel_path"]
        source = args.source_root / rel
        if source.exists():
            return _fail(
                f"{source} is now shipped upstream; "
                "move it from missing_upstream to entries"
            )
        missing += 1

    print(f"bundled={bundled} missing_upstream={missing}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
