"""Final projection-format check and content-hash manifest for the board pipeline."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

from acd.adapters.kicad.fab import zip_content_hash
from acd.adapters.kicad.reload import normalized_hash
from acd.core.electrical.projection_format_check import ProjectionKind, check_projections
from acd.core.runtime.fileio import file_sha256
from acd.schema.common import canonical_json_sha256


def write_hash_manifest(
    out_dir: Path,
    revision: str,
    projection_items: Sequence[tuple[Path, ProjectionKind]],
) -> dict[str, str]:
    """Check projection formats, then write hashes.json covering every listed artifact."""
    hashes: dict[str, str] = {}
    projection_checks = check_projections(projection_items, root=out_dir)
    projection_format_path = out_dir / "projection-format-check.json"
    projection_format_record: dict[str, object] = {
        "schema_version": "0.1",
        "record_class": "L3",
        "pass_evidence": False,
        "target_revision": revision,
        "checks": projection_checks,
    }
    projection_format_record["content_sha256"] = canonical_json_sha256(projection_format_record)
    projection_format_path.write_text(
        json.dumps(projection_format_record, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    hash_paths = [*(path for path, _ in projection_items), projection_format_path]
    print(
        f"[12/12] projection format check: {len(projection_checks)} projections ok "
        f"-> {projection_format_path}"
    )
    for path in hash_paths:
        if path.suffix == ".zip":
            content_hash = zip_content_hash(path)
        elif path.suffix == ".mid":
            content_hash = file_sha256(path)
        else:
            content_hash = normalized_hash(path)
        hashes[str(path.relative_to(out_dir))] = content_hash
    manifest_path = out_dir / "hashes.json"
    manifest_path.write_text(json.dumps(hashes, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"[12/12] hash manifest: {manifest_path}")
    return hashes
