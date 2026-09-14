"""Repository-wide pytest hooks for environment-gated tests."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
GD1_FIXTURE_DIR = REPO_ROOT / "fixtures" / "golden-design-1"

_PINNED_SKIP_REASON = (
    "pinned KiCad footprint library absent; "
    "executed in the container-gates job with ACD_REQUIRE_PINNED_LIBRARY=1"
)
_PINNED_FAIL_REASON = (
    "pinned KiCad footprint library is required in this environment "
    "(container-gates)"
)


def _gd1_pinned_footprints_present() -> bool:
    graph_path = GD1_FIXTURE_DIR / "graph.json"
    if not graph_path.is_file():
        return False
    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    for node in graph["nodes"]:
        if node["kind"] != "electrical.component":
            continue
        footprint_file = node["attrs"].get("footprint_file")
        if not isinstance(footprint_file, str):
            return False
        path = Path(footprint_file)
        if not path.is_absolute():
            # Mirror resolve_fixture_path: fixture dir first, then repo root.
            candidate = GD1_FIXTURE_DIR / path
            path = candidate if candidate.is_file() else REPO_ROOT / path
        if not path.is_file():
            return False
    return True


def pytest_runtest_setup(item: pytest.Item) -> None:
    """Gate pinned-library tests without hiding them behind an import skip.

    On hosts without the pinned KiCad footprint library the marked tests skip;
    with ``ACD_REQUIRE_PINNED_LIBRARY=1`` (container-gates) they fail closed
    instead of silently skipping.
    """
    if item.get_closest_marker("pinned_footprint_library") is None:
        return
    if _gd1_pinned_footprints_present():
        return
    if os.environ.get("ACD_REQUIRE_PINNED_LIBRARY") == "1":
        pytest.fail(_PINNED_FAIL_REASON)
    pytest.skip(_PINNED_SKIP_REASON)
