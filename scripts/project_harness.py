#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "acd @ git+https://github.com/uist1idrju3i/acd-agent@f20514f94d938b73deeb47e6980bbb49501b03c9",
# ]
# ///
"""Project a declared harness into deterministic L3 artifacts."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from io import StringIO
from pathlib import Path

from acd.adapters.svg.harness import generate_harness_visual_projection
from acd.core.electrical import extract_electrical_lane
from acd.schema import DesignGraph, HarnessContract


def _table_rows(contract: HarnessContract) -> list[dict[str, str]]:
    wire_types = {item.wire_type_id: item for item in contract.wire_types}
    return [
        {
            "wire_id": wire.wire_id,
            "net": wire.net_id,
            "wire_type": wire.wire_type_id,
            "cut_length_mm": f"{wire.length_mm + wire.slack_mm:.6f}".rstrip("0").rstrip("."),
            "from": f"{wire.from_.connector_id}:{wire.from_.cavity}",
            "to": f"{wire.to.connector_id}:{wire.to.cavity}",
        }
        for wire in sorted(contract.wires, key=lambda item: item.wire_id)
        if wire.wire_type_id in wire_types
    ]


def _csv(rows: list[dict[str, str]]) -> str:
    buffer = StringIO()
    writer = csv.DictWriter(
        buffer,
        fieldnames=["wire_id", "net", "wire_type", "cut_length_mm", "from", "to"],
        lineterminator="\n",
    )
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


def _markdown(rows: list[dict[str, str]]) -> str:
    lines = [
        "| wire_id | net | wire_type | cut_length_mm | from | to |",
        "|---|---|---|---:|---|---|",
    ]
    lines.extend(
        "| {wire_id} | {net} | {wire_type} | {cut_length_mm} | {from} | {to} |".format(
            **row
        )
        for row in rows
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--graph", required=True, type=Path)
    parser.add_argument("--harness", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    args = parser.parse_args()
    try:
        graph = DesignGraph.model_validate(
            json.loads(args.graph.read_text(encoding="utf-8"))
        )
        contract = HarnessContract.model_validate(
            json.loads(args.harness.read_text(encoding="utf-8"))
        )
        if graph.graph_id != contract.graph_id or graph.revision != contract.revision:
            raise ValueError("harness graph_id/revision does not match graph")
        args.out_dir.mkdir(parents=True, exist_ok=True)
        lane = extract_electrical_lane(graph)
        record = generate_harness_visual_projection(
            out_dir=args.out_dir,
            source_revision=graph.revision,
            graph=graph,
            lane=lane,
            contract=contract,
            authoritative_inputs=(args.graph, args.harness),
            input_base_dir=Path.cwd(),
        )
        rows = _table_rows(contract)
        (args.out_dir / "cut-length-table.csv").write_text(
            _csv(rows), encoding="utf-8"
        )
        (args.out_dir / "cut-length-table.md").write_text(
            _markdown(rows), encoding="utf-8"
        )
        provenance = {
            "artifact_kind": "harness_projection",
            "projection_id": record.projection_id,
            "source_revision": record.source_revision,
            "input_files": [
                item.model_dump(mode="json") for item in record.input_files
            ],
            "renderer": {
                "renderer_type": record.renderer.renderer_type,
                "tool_name": record.renderer.tool_name,
                "tool_version": record.renderer.tool_version,
            },
            "image_hash": record.image_hash,
        }
        (args.out_dir / "harness-projection.provenance.json").write_text(
            json.dumps(provenance, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        print(f"Harness projection input error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
