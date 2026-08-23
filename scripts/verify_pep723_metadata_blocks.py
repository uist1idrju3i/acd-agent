#!/usr/bin/env python3
"""Verify that all ACD-importing scripts share one PEP 723 block."""

from __future__ import annotations

import ast
from pathlib import Path


def _imports_acd(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(alias.name == "acd" or alias.name.startswith("acd.") for alias in node.names):
                return True
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module == "acd" or module.startswith("acd."):
                return True
    return False


def _block(path: Path) -> str:
    source = path.read_text(encoding="utf-8")
    start = source.find("# /// script")
    end = source.find("# ///", start + len("# /// script"))
    if start < 0 or end < 0:
        raise ValueError(f"missing PEP 723 block: {path}")
    return source[start : end + len("# ///")]


def main() -> int:
    paths = sorted(Path("plugins/acd/skills").glob("*/scripts/*.py"))
    paths.append(Path("scripts/probe_pinned_acd_graph.py"))
    blocks = [_block(path) for path in paths if _imports_acd(path)]
    if not blocks:
        raise SystemExit("no ACD-importing scripts found")
    if len(set(blocks)) != 1:
        raise SystemExit("ACD-importing scripts do not share one PEP 723 metadata block")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
