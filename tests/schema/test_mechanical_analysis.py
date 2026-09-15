"""Schema coverage for thermal and FEM estimate contracts."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from acd.schema import FemRequest, ThermalRequest


def test_thermal_request_requires_ambient_or_environment() -> None:
    with pytest.raises(ValidationError):
        ThermalRequest.model_validate(
            {
                "graph_id": "golden-design-1",
                "revision": "r1",
                "sources": [{"refdes": "U2", "tj_max_c": 125}],
                "enclosure": {
                    "wall_thickness_mm": 2,
                    "material": {"k_w_per_mk": 0.25, "source": "manual"},
                },
            }
        )


def test_fem_request_rejects_missing_analysis_load() -> None:
    with pytest.raises(ValidationError):
        FemRequest.model_validate(
            {
                "graph_id": "golden-design-1",
                "revision": "r1",
                "analysis": "drop",
                "mesh": {"source": "generated_shell_box", "element_size_mm": 5},
                "material": {
                    "e_pa": 2.2e9,
                    "nu": 0.39,
                    "rho_kg_m3": 1050,
                    "source": "manual",
                },
                "loads": {},
                "limits": {"max_deflection_mm": 1},
            }
        )
