from typing import Any

import pytest
from pydantic import ValidationError

from acd.schema import PdnAnalysisRequest, PdnResult


def _request() -> dict[str, Any]:
    return {
        "graph_id": "golden-design-1",
        "revision": "r1",
        "paths": [
            {
                "path_id": "p1",
                "net": "VBUS_5V",
                "source_refdes": "J1",
                "sink_refdes": "U2",
                "current_a": 0.5,
                "max_ir_drop_mv": 10.0,
                "max_current_density_a_per_mm2": 100.0,
            }
        ],
        "source": {"kind": "kicad_pcb", "path": "board.kicad_pcb"},
    }


def test_request_uses_copper_defaults() -> None:
    request = PdnAnalysisRequest.model_validate(_request())
    assert request.copper.resistivity_ohm_mm == 1.72e-5
    assert request.copper.temperature_c == 20.0
    assert request.copper.temp_coeff_per_c == 0.00393


def test_request_rejects_duplicate_path_ids() -> None:
    payload = _request()
    payload["paths"] = [payload["paths"][0], payload["paths"][0]]
    with pytest.raises(ValidationError):
        PdnAnalysisRequest.model_validate(payload)


def test_result_requires_deterministic_path_order() -> None:
    with pytest.raises(ValidationError):
        PdnResult.model_validate(
            {
                "graph_id": "golden-design-1",
                "revision": "r1",
                "status": "pass",
                "paths": [
                    {"path_id": "p2", "net": "N", "status": "pass"},
                    {"path_id": "p1", "net": "N", "status": "pass"},
                ],
                "input_hashes": {},
                "tool_versions": {"acd-pdn": "0.1"},
            }
        )


def test_result_authority_is_fixed() -> None:
    result = PdnResult.model_validate(
        {
            "graph_id": "golden-design-1",
            "revision": "r1",
            "status": "unknown",
            "paths": [{"path_id": "p1", "net": "N", "status": "unknown"}],
            "input_hashes": {},
            "tool_versions": {"acd-pdn": "0.1"},
        }
    )
    assert result.authority == "estimate"
