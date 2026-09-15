#!/usr/bin/env python3
"""Convert a declared HIL run into measured PhysicalEvidence."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from acd.schema import (
    HilMeasurementPlan,
    HilRunRecord,
    build_physical_evidence_from_hil,
)


def _load(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--virtual-log", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        plan = HilMeasurementPlan.model_validate(_load(args.plan))
        run = HilRunRecord.model_validate(_load(args.run))
        virtual_log = args.virtual_log.read_text(encoding="utf-8")
        evidence = build_physical_evidence_from_hil(
            plan,
            run,
            virtual_log=virtual_log,
        )
    except Exception as exc:
        print(f"HIL input error: {exc}", file=sys.stderr)
        return 2
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(
            evidence.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return 0 if evidence.supports_measured_claim(plan.revision) else 1


if __name__ == "__main__":
    raise SystemExit(main())
