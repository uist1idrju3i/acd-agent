"""Visual projection generation and crosscheck for the electrical, mechanical, and firmware lanes.

Projections are derived after deterministic gates and never flow back into design inputs.
"""

from __future__ import annotations

from acd.pipeline.visual_projection.electrical import (
    crosscheck_electrical_visual_projections,
    derive_png_visual_projections,
    generate_electrical_visual_projections,
)
from acd.pipeline.visual_projection.firmware import crosscheck_firmware_visual_projections
from acd.pipeline.visual_projection.mechanical import crosscheck_mechanical_visual_projections

__all__ = [
    "crosscheck_electrical_visual_projections",
    "crosscheck_firmware_visual_projections",
    "crosscheck_mechanical_visual_projections",
    "derive_png_visual_projections",
    "generate_electrical_visual_projections",
]
