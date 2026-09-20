"""Check whether a workaround can be retired after an ECO."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import cast

from acd.core.manufacturing.workaround_ledger import evaluate_workaround_retirement
from acd.schema.defect_record import DefectDocument
from acd.schema.design_graph import DesignGraph
from acd.schema.eco import EcoCheckResult, EcoDocument, EcoRecord
from acd.schema.rework_diff import ReworkDiff
from acd.schema.workaround_ledger import WorkaroundLedger


def _load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_eco(path: Path) -> EcoDocument:
    payload = _load_json(path)
    body = cast(dict[str, object], payload) if isinstance(payload, dict) else {}
    if body.get("artifact_kind") == "eco":
        return EcoDocument(ecos=[EcoRecord.model_validate(body)])
    return EcoDocument.model_validate(payload)


def _load_eco_check(
    path: Path,
) -> tuple[EcoCheckResult | None, str | None, str | None]:
    if not path.is_file():
        return None, None, None
    try:
        raw = path.read_bytes()
        digest = f"sha256:{hashlib.sha256(raw).hexdigest()}"
        return EcoCheckResult.model_validate_json(raw), digest, None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        return None, None, f"eco-check.json is malformed: {exc}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--workaround-id", required=True)
    parser.add_argument("--defects", type=Path, required=True)
    parser.add_argument("--rework", type=Path, required=True)
    parser.add_argument("--eco", type=Path, required=True)
    parser.add_argument("--eco-id", required=True)
    parser.add_argument("--eco-check", type=Path, required=True)
    parser.add_argument("--to-graph", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args(argv)

    try:
        ledger = WorkaroundLedger.model_validate(_load_json(args.ledger))
        defects = DefectDocument.model_validate(_load_json(args.defects))
        rework = ReworkDiff.model_validate(_load_json(args.rework))
        eco_document = _load_eco(args.eco)
        to_graph = DesignGraph.model_validate(_load_json(args.to_graph))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    eco_check, eco_check_sha256, eco_check_error = _load_eco_check(args.eco_check)
    if eco_check is not None and eco_check.eco_id != args.eco_id:
        eco_check_error = "eco-check ECO ID does not match requested ECO ID"
    result = evaluate_workaround_retirement(
        ledger=ledger,
        workaround_id=args.workaround_id,
        defects=defects,
        rework=rework,
        eco_document=eco_document,
        eco_id=args.eco_id,
        eco_check=eco_check,
        eco_check_sha256=eco_check_sha256,
        eco_check_error=eco_check_error,
        to_graph=to_graph,
    )
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "workaround-retirement-check.json").write_text(
        result.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0 if result.verdict == "retired" else 1


if __name__ == "__main__":
    raise SystemExit(main())
