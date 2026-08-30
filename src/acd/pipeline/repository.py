"""Repository paths shared by deterministic pipeline modules."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def repository_root() -> Path:
    configured_root = os.environ.get("ACD_REPOSITORY_ROOT")
    root = (
        Path(configured_root)
        if configured_root is not None
        else Path(__file__).resolve().parents[3]
    )
    required_markers = (root / "AGENTS.md", root / "pyproject.toml")
    missing = [str(path) for path in required_markers if not path.is_file()]
    if missing:
        raise RuntimeError(
            "repository root validation failed: "
            f"{root} is missing required marker(s): {', '.join(missing)}"
        )
    return root


def resolve_repository_file(path: str | Path) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = repository_root() / candidate
    if not candidate.is_file():
        raise RuntimeError(f"repository file is unavailable: {candidate}")
    return candidate


__all__ = ["repository_root", "resolve_repository_file"]
