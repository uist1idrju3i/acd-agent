"""Tests for host/container output separation and failure classification."""

from __future__ import annotations

from pathlib import Path

import pytest

from acd.openhands.execution_failure import classify_execution_failure
from acd.openhands.workspace import (
    CONTAINER_OUT_ROOT,
    container_download_destination,
)


def test_container_outputs_land_in_their_own_out_root(tmp_path: Path) -> None:
    destination = container_download_destination(
        tmp_path, "out/gd1/evidence-electrical.json"
    )
    assert destination == tmp_path / CONTAINER_OUT_ROOT / "gd1/evidence-electrical.json"
    assert destination != tmp_path / "out/gd1/evidence-electrical.json"


def test_non_output_download_paths_are_unchanged(tmp_path: Path) -> None:
    assert container_download_destination(tmp_path, "reports/a.json") == (
        tmp_path / "reports/a.json"
    )


def test_absolute_download_path_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="repository-relative"):
        container_download_destination(tmp_path, "/out/gd1/evidence.json")


@pytest.mark.parametrize(
    "output",
    [
        "mkdir: cannot create directory 'out': Permission denied",
        "OSError: [Errno 13] Permission denied: 'out/gd1'",
        "error: Read-only file system",
    ],
)
def test_permission_failures_are_not_design_failures(output: str) -> None:
    assert classify_execution_failure(1, output) == "permission"


def test_environment_failures_are_separated_from_design_failures() -> None:
    assert classify_execution_failure(1, "error: No space left on device") == (
        "environment"
    )
    assert classify_execution_failure(1, "failed to create cache directory") == (
        "environment"
    )


def test_design_rejection_stays_a_design_failure() -> None:
    assert classify_execution_failure(1, "PIPELINE FAILED: DRC violations") == "design"


def test_success_and_silent_failure_are_distinguished() -> None:
    assert classify_execution_failure(0, "") == "none"
    assert classify_execution_failure(2, "   ") == "unknown"
