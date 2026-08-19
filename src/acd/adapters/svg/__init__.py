"""Deterministic repository-local SVG projection adapters."""

from acd.adapters.svg.common import (
    ACD_SVG_NORMALIZATION_RULE_DESCRIPTION,
    ACD_SVG_NORMALIZATION_RULE_ID,
    ACD_SVG_RENDERER_VERSION,
    SvgVisualProjectionError,
)
from acd.adapters.svg.layout import (
    SvgLayoutRenderer,
    generate_layout_visual_projections,
)
from acd.adapters.svg.system import (
    SvgSystemRenderer,
    generate_system_visual_projections,
)

__all__ = [
    "ACD_SVG_NORMALIZATION_RULE_DESCRIPTION",
    "ACD_SVG_NORMALIZATION_RULE_ID",
    "ACD_SVG_RENDERER_VERSION",
    "SvgLayoutRenderer",
    "SvgSystemRenderer",
    "SvgVisualProjectionError",
    "generate_layout_visual_projections",
    "generate_system_visual_projections",
]
