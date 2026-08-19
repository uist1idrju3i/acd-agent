"""Deterministic repository-local SVG projection adapters."""

from acd.adapters.svg.layout import (
    ACD_SVG_NORMALIZATION_RULE_DESCRIPTION,
    ACD_SVG_NORMALIZATION_RULE_ID,
    ACD_SVG_RENDERER_VERSION,
    LayoutVisualProjectionError,
    SvgLayoutRenderer,
    generate_layout_visual_projections,
)

__all__ = [
    "ACD_SVG_NORMALIZATION_RULE_DESCRIPTION",
    "ACD_SVG_NORMALIZATION_RULE_ID",
    "ACD_SVG_RENDERER_VERSION",
    "LayoutVisualProjectionError",
    "SvgLayoutRenderer",
    "generate_layout_visual_projections",
]
