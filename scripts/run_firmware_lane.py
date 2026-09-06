"""Run the virtual firmware lane and record ``evidence-firmware.json``."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from acd.pipeline.firmware_lane import FirmwareLaneError, run_firmware_lane
from acd.schema import DesignGraph


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fixture",
        type=Path,
        required=True,
        help="fixture directory containing graph.json",
    )
    parser.add_argument(
        "--out",
        type=Path,
        required=True,
        help="output directory for the firmware lane artifacts and Evidence",
    )
    parser.add_argument(
        "--run-seconds",
        type=int,
        default=15,
        help="virtual run duration passed to the firmware Skill",
    )
    parser.add_argument(
        "--repo",
        type=Path,
        default=Path.cwd(),
        help="repository root that contains the firmware Skill script",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the firmware lane; print a one-line JSON result."""
    args = _parser().parse_args(argv)
    try:
        result = run_firmware_lane(
            args.repo,
            args.fixture,
            args.out,
            run_seconds=args.run_seconds,
        )
    except FirmwareLaneError as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "fail_closed": True,
                    "stage": "firmware-pipeline",
                    "reason": str(exc),
                },
                ensure_ascii=False,
            )
        )
        print(str(exc), file=sys.stderr)
        return 1
    graph = DesignGraph.model_validate_json(
        (args.fixture / "graph.json").read_text(encoding="utf-8")
    )
    print(
        json.dumps(
            {
                "ok": True,
                "output_path": str(result.output_path),
                "evidence_path": str(result.evidence_path),
                "evidence_authoritative": result.evidence.supports_authoritative_pass(
                    graph.revision
                ),
                "evidence_provisional": result.evidence.is_provisional(),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
