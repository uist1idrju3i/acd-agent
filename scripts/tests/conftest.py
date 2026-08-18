"""Configure imports for script tests."""

import json
import sys
from pathlib import Path
from typing import Any, cast

sys.path.insert(0, str(Path(__file__).parents[2]))

REPO_ROOT = Path(__file__).parents[2]


def load_fixture(kind: str, name: str) -> dict[str, Any]:
    """Load a contract fixture for tests collected with script tests."""
    value = cast(
        dict[str, Any],
        json.loads((REPO_ROOT / "fixtures/contracts" / kind / name).read_text()),
    )
    assert isinstance(value, dict)
    return value


def fixture_obj(value: Any) -> dict[str, Any]:
    """Assert and return a fixture object."""
    assert isinstance(value, dict)
    return cast(dict[str, Any], value)
