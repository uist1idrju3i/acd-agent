"""KiCad copper-layer naming helpers."""

from __future__ import annotations

_KICAD_COPPER_LAYERS_BY_COUNT: dict[int, tuple[str, ...]] = {
    2: ("F.Cu", "B.Cu"),
    4: ("F.Cu", "In1.Cu", "In2.Cu", "B.Cu"),
}


def copper_layers_for_layer_count(layer_count: int) -> tuple[str, ...]:
    """Return KiCad copper-layer names for a supported board layer count."""
    if isinstance(layer_count, bool) or layer_count not in _KICAD_COPPER_LAYERS_BY_COUNT:
        raise ValueError(f"unsupported KiCad copper layer count: {layer_count!r}")
    return _KICAD_COPPER_LAYERS_BY_COUNT[layer_count]
