#!/usr/bin/env python3
"""Run the opt-in board/component/enclosure 3D integration."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from acd.adapters.cad.component_3d import (
    check_assembly_interference_3d,
    import_component_step,
)
from acd.adapters.cad.project import project_enclosure
from acd.adapters.kicad.step_export import export_board_step
from acd.core.electrical import extract_electrical_lane
from acd.core.mechanical import extract_mechanical_lane
from acd.schema.design_graph import DesignGraph


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graph", type=Path, required=True)
    parser.add_argument("--pcb", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--step", type=Path)
    parser.add_argument("--models-dir", type=Path, default=Path("/opt/acd/kicad-3d"))
    parser.add_argument("--kicad-cli", default="kicad-cli")
    args = parser.parse_args(argv)
    try:
        args.out.mkdir(parents=True, exist_ok=True)
        graph = DesignGraph.model_validate(
            json.loads(args.graph.read_text(encoding="utf-8"))
        )
        fixture_dir = args.graph.parent
        lane = extract_mechanical_lane(graph)
        electrical = extract_electrical_lane(graph)
        refdes = {component.node_id: component.refdes for component in electrical.components}
        step = args.step
        export = None
        if step is None:
            step = args.out / "component-board.step"
            export = export_board_step(
                args.pcb,
                step,
                kicad_cli=args.kicad_cli,
                models_dir=args.models_dir,
            )
            if export.status != "pass":
                (args.out / "component-3d.json").write_text(
                    json.dumps({"status": export.status, "error": export.error}, indent=2) + "\n",
                    encoding="utf-8",
                )
                return 1
        projection = project_enclosure(
            lane,
            graph_path=args.graph,
            out_dir=args.out / "enclosure",
            target_revision=graph.revision,
            graph_id=graph.graph_id,
        )
        imported = import_component_step(step, lane, refdes_by_component_id=refdes)
        build123d = __import__("build123d")
        report = check_assembly_interference_3d(
            imported,
            shell=build123d.import_step(projection.shell_step_path),
            lid=build123d.import_step(projection.lid_step_path),
            lane=lane,
        )
        record = {
            "status": report.status,
            "step": str(step),
            "model_hash": imported.model_hash,
            "findings": [
                {
                    "rule_id": item.rule_id,
                    "status": item.status,
                    "message": item.message,
                    "refdes": item.refdes,
                    "body_id": item.body_id,
                }
                for item in report.findings
            ],
            "export": (
                {
                    "status": export.status,
                    "pcb_sha256": export.pcb_sha256,
                    "model_directory_sha256": export.model_directory_sha256,
                    "kicad_version": export.kicad_version,
                    "output_step_sha256": export.output_step_sha256,
                }
                if export is not None
                else None
            ),
            "fixture_dir": str(fixture_dir),
        }
        (args.out / "component-3d.json").write_text(
            json.dumps(record, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return 0 if report.status == "pass" else 1
    except (OSError, UnicodeError, ValueError, RuntimeError, ImportError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
