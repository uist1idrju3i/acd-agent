from typing import Any

import pytest
from pydantic import ValidationError

from acd.schema import SpiceAnalysisRequest, SpiceResult


def _request() -> dict[str, Any]:
    return {
        "graph_id": "golden-design-1",
        "revision": "r1",
        "models": {
            "ldo": {
                "refdes": "U2",
                "vout_v": 3.3,
                "dropout_v": 1.1,
                "iq_a": 0.005,
            }
        },
        "sources": {"vbus_v": 5.0, "vbus_ramp_ms": 0.1},
        "analyses": [{"kind": "op"}, {"kind": "tran", "tstep": 1e-9, "tstop": 1e-6}],
        "limits": [{"quantity": "node_voltage", "target": "+3V3", "min": 3.2}],
        "ngspice": {"version_pin": "45.2"},
    }


def test_request_requires_transient_parameters() -> None:
    payload = _request()
    payload["analyses"] = [{"kind": "tran"}]
    with pytest.raises(ValidationError):
        SpiceAnalysisRequest.model_validate(payload)


def test_result_authority_is_fixed() -> None:
    result = SpiceResult.model_validate(
        {
            "graph_id": "golden-design-1",
            "revision": "r1",
            "status": "unknown",
            "checks": [
                {
                    "quantity": "node_voltage",
                    "target": "+3V3",
                    "status": "unknown",
                    "reason": "tool missing",
                }
            ],
            "netlist_sha256": "sha256:" + "a" * 64,
            "raw_output_sha256": "unknown",
            "ngspice_version": "unknown",
            "input_hashes": {},
        }
    )
    assert result.authority == "estimate"
