# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "acd @ git+https://github.com/uist1idrju3i/acd-agent@678de246c31ee0822ddbfca0cab689ed7df297cf",
# ]
# ///
"""Measure CAD export determinism for STEP and 3MF.

The measurement re-exports the same solid twice, hashes the raw bytes, and
hashes the normalized bytes produced by ``acd.core.cad_normalize``. It records
what differs between two runs and which normalization rule removes it.

This is a measurement record, not a gate. Pass/fail for a design is decided by
the ACD gates (ERC/DRC, mechanical gates, independent reload) alone.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from acd.core.cad_normalize import normalize_3mf, normalize_step


@dataclass(frozen=True)
class CadFormatMeasurement:
    """Measured determinism and normalization result for one CAD format."""

    format: str
    raw_equal: bool
    normalized_equal: bool
    raw_hashes: list[str]
    normalized_hashes: list[str]
    differences: list[str]
    normalization_rule: str


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _export_3mf(shape: Any, path: Path) -> None:
    build123d: Any = importlib.import_module("build123d")
    mesher = build123d.Mesher()
    mesher.add_shape(shape, linear_deflection=0.01, angular_deflection=0.1, part_number="box")
    mesher.write(path)


def measure_cad_exports() -> list[CadFormatMeasurement]:
    """Export the same box twice per format and compare raw and normalized bytes."""
    build123d: Any = importlib.import_module("build123d")

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        shape = build123d.Box(10, 10, 10)
        build123d.export_step(shape, root / "first.step")
        # STEP embeds a one-second-resolution FILE_NAME timestamp.
        time.sleep(1.1)
        build123d.export_step(shape, root / "second.step")
        step_a = (root / "first.step").read_bytes()
        step_b = (root / "second.step").read_bytes()
        _export_3mf(shape, root / "first.3mf")
        _export_3mf(shape, root / "second.3mf")
        mf_a = (root / "first.3mf").read_bytes()
        mf_b = (root / "second.3mf").read_bytes()

    normalized_step_a = normalize_step(step_a)
    normalized_step_b = normalize_step(step_b)
    normalized_mf_a = normalize_3mf(mf_a)
    normalized_mf_b = normalize_3mf(mf_b)
    return [
        CadFormatMeasurement(
            format="STEP",
            raw_equal=step_a == step_b,
            normalized_equal=normalized_step_a == normalized_step_b,
            raw_hashes=[_sha256(step_a), _sha256(step_b)],
            normalized_hashes=[_sha256(normalized_step_a), _sha256(normalized_step_b)],
            differences=["FILE_NAME timestamp"] if step_a != step_b else [],
            normalization_rule="Replace FILE_NAME timestamp with 1970-01-01T00:00:00.",
        ),
        CadFormatMeasurement(
            format="3MF",
            raw_equal=mf_a == mf_b,
            normalized_equal=normalized_mf_a == normalized_mf_b,
            raw_hashes=[_sha256(mf_a), _sha256(mf_b)],
            normalized_hashes=[_sha256(normalized_mf_a), _sha256(normalized_mf_b)],
            differences=["3D/3dmodel.model p:UUID attributes"] if mf_a != mf_b else [],
            normalization_rule=(
                "Replace all 3D/3dmodel.model p:UUID values and canonicalize ZIP entry timestamps."
            ),
        ),
    ]


def main() -> int:
    measurements = [asdict(measurement) for measurement in measure_cad_exports()]
    print(json.dumps({"cad_formats": measurements}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
