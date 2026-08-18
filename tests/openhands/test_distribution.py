"""Tests for the standard package distribution route."""

from __future__ import annotations

import subprocess
import zipfile
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
LOCK_PATH = REPOSITORY_ROOT / "docker" / "image-digests.json"


def test_wheel_contains_the_tracked_image_lock(tmp_path: Path) -> None:
    result = subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(tmp_path)],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr

    wheels = sorted(tmp_path.glob("*.whl"))
    assert len(wheels) == 1
    with zipfile.ZipFile(wheels[0]) as wheel:
        assert wheel.read("acd/openhands/image-digests.json") == LOCK_PATH.read_bytes()
