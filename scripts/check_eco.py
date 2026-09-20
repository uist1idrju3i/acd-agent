"""Run the deterministic close gate for an ECO record."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import cast

from acd.core.knowledge.eco_gate import EcoGateError, evaluate_eco
from acd.schema.defect_record import DefectDocument
from acd.schema.design_graph import DesignGraph
from acd.schema.eco import EcoDocument, EcoRecord


def _load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_graph(path: Path) -> DesignGraph:
    return DesignGraph.model_validate(_load_json(path))


def _load_eco(path: Path) -> EcoDocument:
    payload = _load_json(path)
    body = cast(dict[str, object], payload) if isinstance(payload, dict) else {}
    if body.get("artifact_kind") == "eco":
        record = EcoRecord.model_validate(body)
        return EcoDocument(ecos=[record])
    return EcoDocument.model_validate(payload)


def _load_defects(path: Path) -> DefectDocument:
    return DefectDocument.model_validate(_load_json(path))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--eco", type=Path, required=True)
    parser.add_argument("--eco-id", required=True)
    parser.add_argument("--from-graph", type=Path, required=True)
    parser.add_argument("--to-graph", type=Path, required=True)
    parser.add_argument("--defects", type=Path, required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args(argv)

    try:
        eco_document = _load_eco(args.eco)
        from_graph = _load_graph(args.from_graph)
        to_graph = _load_graph(args.to_graph)
        defects = _load_defects(args.defects)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    try:
        result = evaluate_eco(
            eco_document=eco_document,
            eco_id=args.eco_id,
            from_graph=from_graph,
            to_graph=to_graph,
            defects=defects,
            evidence_dir=args.evidence_dir,
        )
    except EcoGateError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "eco-check.json").write_text(
        result.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0 if result.verdict == "closable" else 1


if __name__ == "__main__":
    raise SystemExit(main())
