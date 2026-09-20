"""Compatibility re-export.

The implementation lives in ``acd.core.electrical.visual_projection``.
"""

from acd.core.electrical.visual_projection import (
    ACD_SVG_NORMALIZATION_RULE_ID,
    BYTE_EXACT_SVG_NORMALIZATION_RULE_IDS,
    CAD_SVG_NORMALIZATION_RULE_ID,
    KICAD_LAYER_SVG_NORMALIZATION_RULE_DESCRIPTION,
    KICAD_LAYER_SVG_NORMALIZATION_RULE_ID,
    SVG_TITLE_NORMALIZATION_RULE_DESCRIPTION,
    SVG_TITLE_NORMALIZATION_RULE_ID,
    LayerViewAnnotations,
    MeasuredSvgResolution,
    SvgNormalizationError,
    SvgResolutionError,
    cad_view_geometry,
    measure_svg_resolution,
    nested_view_attributes,
    nested_view_geometry,
    normalize_kicad_layer_svg,
    normalize_svg,
    normalized_svg_sha256,
    raw_svg_parts,
    svg_source_hash,
)

__all__ = [
    "ACD_SVG_NORMALIZATION_RULE_ID",
    "BYTE_EXACT_SVG_NORMALIZATION_RULE_IDS",
    "CAD_SVG_NORMALIZATION_RULE_ID",
    "KICAD_LAYER_SVG_NORMALIZATION_RULE_DESCRIPTION",
    "KICAD_LAYER_SVG_NORMALIZATION_RULE_ID",
    "SVG_TITLE_NORMALIZATION_RULE_DESCRIPTION",
    "SVG_TITLE_NORMALIZATION_RULE_ID",
    "LayerViewAnnotations",
    "MeasuredSvgResolution",
    "SvgNormalizationError",
    "SvgResolutionError",
    "cad_view_geometry",
    "measure_svg_resolution",
    "nested_view_attributes",
    "nested_view_geometry",
    "normalize_kicad_layer_svg",
    "normalize_svg",
    "normalized_svg_sha256",
    "raw_svg_parts",
    "svg_source_hash",
]
