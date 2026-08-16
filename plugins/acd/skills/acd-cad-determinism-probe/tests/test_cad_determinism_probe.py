"""CAD determinism measurement tests (skill asset, separate from the ACD core)."""

from __future__ import annotations

import importlib.util

import pytest

from cad_determinism_probe import measure_cad_exports

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("build123d") is None,
    reason="build123d is not installed",
)


def test_measurement_covers_both_formats_and_normalizes_them() -> None:
    measurements = measure_cad_exports()
    assert [measurement.format for measurement in measurements] == ["STEP", "3MF"]
    for measurement in measurements:
        assert measurement.normalized_equal
        assert len(measurement.raw_hashes) == 2
        assert len(measurement.normalized_hashes) == 2
        assert measurement.normalized_hashes[0] == measurement.normalized_hashes[1]
        assert measurement.normalization_rule
