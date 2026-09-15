#!/usr/bin/env python3
"""Run the fail-closed firmware security build consistency gate."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from acd.core.fw_security_gate import check_build_config_consistency
from acd.schema.design_graph import DesignGraph
from acd.schema.fw_security import FirmwareSecurityDeclaration


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--declaration", type=Path, required=True)
    parser.add_argument("--sdkconfig", type=Path, required=True)
    parser.add_argument("--partitions", type=Path, required=True)
    parser.add_argument("--size-json", type=Path)
    parser.add_argument("--graph", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        declaration = FirmwareSecurityDeclaration.model_validate_json(
            args.declaration.read_text(encoding="utf-8")
        )
        if args.graph is not None:
            graph = DesignGraph.model_validate_json(
                args.graph.read_text(encoding="utf-8")
            )
            if (
                declaration.graph_id != graph.graph_id
                or declaration.revision != graph.revision
            ):
                raise ValueError("firmware security declaration revision mismatch")
        result = check_build_config_consistency(
            declaration,
            args.sdkconfig,
            args.partitions,
            size_json_path=args.size_json,
        )
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            result.model_dump_json(indent=2) + "\n",
            encoding="utf-8",
        )
    except Exception as exc:
        print(f"firmware security input error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result.model_dump(mode="json"), ensure_ascii=False))
    return 0 if result.status == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
