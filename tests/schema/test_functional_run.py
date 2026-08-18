"""Tests for the firmware functional-run contract."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from acd.schema import FunctionalRunRecord

ROOT = Path(__file__).parents[2]


def load_run(kind: str, name: str = "run.json") -> dict[str, object]:
    return json.loads(
        (ROOT / "fixtures/functional" / kind / name).read_text(encoding="utf-8")
    )


def test_valid_functional_run_fixture() -> None:
    run = FunctionalRunRecord.model_validate(load_run("valid"))
    assert run.measurement_class == "measured"
    assert len(run.build_artifacts) == 2
    assert len(run.logs) == 4
    assert run.app_flash_offset == 65536
    assert run.serial_log_tag == "gd1"


@pytest.mark.parametrize(
    "variant",
    ["idf-unknown", "time-reversed"],
)
def test_invalid_functional_run_contract_fails_closed(variant: str) -> None:
    with pytest.raises(ValidationError):
        FunctionalRunRecord.model_validate(load_run(f"invalid/{variant}"))


def test_functional_run_rejects_duplicate_paths() -> None:
    value = load_run("valid")
    artifacts = value["build_artifacts"]
    assert isinstance(artifacts, list)
    assert isinstance(artifacts[1], dict)
    artifacts[1]["path"] = artifacts[0]["path"]
    with pytest.raises(ValidationError):
        FunctionalRunRecord.model_validate(value)
