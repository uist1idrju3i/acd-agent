from __future__ import annotations

from typing import cast

import pytest
from pydantic import ValidationError

from acd.schema import FirmwareAnalysisResult


def _result() -> dict[str, object]:
    return {
        "graph_id": "golden-design-1",
        "revision": "r1",
        "status": "pass",
        "input_hashes": {},
        "peripheral_sim": {
            "status": "pass",
            "scenario_sha256": "sha256:" + "a" * 64,
            "samples": [{"t_c": 25.0, "rh_pct": 40.0}],
        },
    }


def test_firmware_analysis_preserves_nested_observation_authority() -> None:
    result = FirmwareAnalysisResult.model_validate(_result())
    assert result.authority == "estimate"
    assert result.peripheral_sim is not None
    assert result.peripheral_sim.authority == "observation"


def test_firmware_analysis_rejects_authoritative_peripheral() -> None:
    payload = _result()
    peripheral = (
        cast(dict[str, object], payload["peripheral_sim"])
        if isinstance(payload["peripheral_sim"], dict)
        else {}
    )
    peripheral["authority"] = "authoritative"
    payload["peripheral_sim"] = peripheral
    with pytest.raises(ValidationError):
        FirmwareAnalysisResult.model_validate(payload)
