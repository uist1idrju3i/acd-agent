"""Collect the declared minimal lane artifact set into a destination directory.

Reads ``contracts/lane-artifact-retention.json`` (or a given contract) and
copies each matched minimal artifact to ``<dest>/<lane_id>/<relative path>``.
Regenerable outputs are never copied. Missing required patterns fail closed:
the manifest is still written and the exit code is 1.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from acd.core.runtime.lane_artifact_retention import (
    AUTHORITY_STATEMENT,
    LaneArtifactRetentionError,
    load_lane_artifact_retention,
    resolve_lane_retention,
)
from acd.pipeline.lane_plan import build_lane_plan


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out-root",
        type=Path,
        required=True,
        help="root directory containing the lane outputs",
    )
    parser.add_argument(
        "--graph-id",
        required=True,
        help="graph ID used to rebuild the lane plan",
    )
    parser.add_argument(
        "--dest",
        type=Path,
        required=True,
        help="destination directory for the retained minimal set",
    )
    parser.add_argument(
        "--lane",
        action="append",
        default=None,
        help="restrict collection to the given lane ID (repeatable)",
    )
    parser.add_argument(
        "--contract",
        type=Path,
        default=None,
        help="override the retention contract path",
    )
    return parser


def collect(
    graph_id: str,
    out_root: Path,
    dest: Path,
    *,
    lanes: Sequence[str] | None = None,
    contract: Path | None = None,
) -> dict[str, Any]:
    """Copy declared minimal artifacts and write the retention manifest."""
    declaration = load_lane_artifact_retention(contract)
    plan = build_lane_plan(graph_id, out_root)
    selected = set(lanes) if lanes else None
    reports: list[dict[str, Any]] = []
    missing: list[str] = []
    for stage in plan.lane_runner_stages:
        if stage.output_path is None:
            continue
        if selected is not None and stage.stage_id not in selected:
            continue
        if not stage.output_path.is_dir():
            reports.append(
                {
                    "lane_id": stage.stage_id,
                    "output_path": str(stage.output_path),
                    "status": "output_missing",
                }
            )
            missing.append(f"{stage.stage_id}: output_missing")
            continue
        report = resolve_lane_retention(
            stage.stage_id, stage.output_path, declaration
        )
        for item in report.retained:
            source = stage.output_path / item.path
            target = dest / stage.stage_id / item.path
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        body = report.to_dict()
        reports.append(body)
        missing.extend(
            f"{stage.stage_id}: {pattern}" for pattern in body["missing_required"]
        )
    if selected is not None:
        unknown = sorted(selected - {stage.stage_id for stage in plan.lane_runner_stages})
        if unknown:
            raise LaneArtifactRetentionError(
                f"unknown lane selector(s): {', '.join(unknown)}"
            )
    manifest = {
        "schema_version": "0.1",
        "declaration_hash": declaration.declaration_hash,
        "lanes": reports,
        "pass_evidence": False,
        "record_class": "L3",
        "authority_statement": AUTHORITY_STATEMENT,
    }
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "retention-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        manifest = collect(
            args.graph_id,
            args.out_root,
            args.dest,
            lanes=args.lane,
            contract=args.contract,
        )
    except (OSError, LaneArtifactRetentionError, ValueError) as exc:
        print(f"COLLECTION FAILED (fail-closed): {exc}", file=sys.stderr)
        return 1
    missing = [
        f"{lane['lane_id']}: {pattern}"
        for lane in manifest["lanes"]
        for pattern in lane.get("missing_required", [])
    ]
    missing.extend(
        f"{lane['lane_id']}: output_missing"
        for lane in manifest["lanes"]
        if lane.get("status") == "output_missing"
    )
    if missing:
        print(
            "COLLECTION FAILED (fail-closed): missing required artifacts: "
            + "; ".join(missing),
            file=sys.stderr,
        )
        return 1
    print(json.dumps(manifest, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
