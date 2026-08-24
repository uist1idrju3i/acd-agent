# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "acd @ git+https://github.com/uist1idrju3i/acd-agent@3153a012e008621e8f30711ed54cddf97f6b21ca",
# ]
# ///
"""Validate a fixture with the pinned ACD package and exercise the FW Skill."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

from pydantic import ValidationError

from acd.schema.design_graph import DesignGraph


def _load_fw_graph() -> ModuleType:
    path = (
        Path(__file__).resolve().parent.parent
        / "plugins"
        / "acd"
        / "skills"
        / "acd-firmware-esp32c3"
        / "scripts"
        / "fw_graph.py"
    )
    spec = importlib.util.spec_from_file_location("acd_pinned_fw_graph", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load firmware Skill script: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        graph_path = args.fixture / "graph.json"
        graph = DesignGraph.model_validate(json.loads(graph_path.read_text(encoding="utf-8")))
        fw_graph = _load_fw_graph()
        lane = fw_graph.extract_firmware_lane(graph)
        summary = {
            "revision": graph.revision,
            "node_count": len(graph.nodes),
            "pin_count": len(lane.pins),
        }
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
        return 0
    except (
        ValidationError,
        OSError,
        json.JSONDecodeError,
        ValueError,
        RuntimeError,
    ) as error:
        print(f"ERROR: pinned ACD graph probe failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
