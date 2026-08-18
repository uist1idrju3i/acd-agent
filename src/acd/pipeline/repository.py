"""Repository paths shared by deterministic pipeline modules."""

from __future__ import annotations

from pathlib import Path


def _resolve_repository_root() -> Path:
    root = Path(__file__).resolve().parents[3]
    required_markers = (root / "AGENTS.md", root / "pyproject.toml")
    missing = [str(path) for path in required_markers if not path.is_file()]
    if missing:
        raise RuntimeError(
            "repository root validation failed: "
            f"{root} is missing required marker(s): {', '.join(missing)}"
        )
    return root


REPO_ROOT = _resolve_repository_root()

__all__ = ["REPO_ROOT"]
