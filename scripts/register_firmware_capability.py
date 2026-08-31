"""Validate and register one firmware capability declaration."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from acd.core.firmware_capability import FirmwareCapabilityContractError
from acd.core.firmware_capability_entry import register_firmware_capability


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--capability",
        required=True,
        help="FirmwareCapabilityContract JSON path or inline JSON object.",
    )
    parser.add_argument(
        "--registry",
        type=Path,
        default=Path("contracts/firmware-capability-registry.json"),
        help="Firmware capability registry path.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate without writing the registry.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = register_firmware_capability(
            args.capability,
            args.registry,
            dry_run=args.dry_run,
        )
        payload = {"ok": True, **result.model_dump()}
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except (FirmwareCapabilityContractError, OSError, TypeError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "fail_closed": True,
                    "failure_reason": str(exc),
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
