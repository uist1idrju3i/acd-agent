"""Export the publishable minimum set of execution records with redaction on."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import cast

from acd.core.runtime.execution_export import ExecutionExportError, export_execution_record
from acd.core.runtime.lane_log import LaneLogError, parse_lane_log


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "records",
        nargs="+",
        type=Path,
        help="execution record JSON files (or directories of *.json records)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        required=True,
        help="file that receives the sanitized publishable export",
    )
    return parser


def _record_paths(inputs: Sequence[Path]) -> list[Path]:
    paths: list[Path] = []
    for entry in inputs:
        if entry.is_dir():
            paths.extend(
                path
                for path in entry.iterdir()
                if path.is_file() and path.suffix in {".json", ".log"}
            )
        else:
            paths.append(entry)
    return sorted(paths)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    exported: list[dict[str, object]] = []
    for path in _record_paths(args.records):
        if path.suffix == ".log":
            try:
                body = parse_lane_log(
                    path.read_text(encoding="utf-8")
                ).to_execution_record()
            except (OSError, LaneLogError) as error:
                print(f"{path}: lane log could not be read: {error}", file=sys.stderr)
                return 2
        else:
            try:
                body = cast(object, json.loads(path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError) as error:
                print(
                    f"{path}: record could not be read: {error}", file=sys.stderr
                )
                return 2
        if not isinstance(body, dict):
            print(f"{path}: record must be a JSON object", file=sys.stderr)
            return 2
        try:
            exported.append(
                export_execution_record(cast(dict[str, object], body))
            )
        except ExecutionExportError as error:
            print(f"{path}: {error}", file=sys.stderr)
            return 1
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(exported, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"exported {len(exported)} record(s) to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
