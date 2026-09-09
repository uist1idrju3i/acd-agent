"""Deterministic ISO paper selection for content-fitted sheets."""

from __future__ import annotations

# Landscape ISO series: (name, long side mm, short side mm).
ISO_PAPER_LANDSCAPE_MM: tuple[tuple[str, float, float], ...] = (
    ("A4", 297.0, 210.0),
    ("A3", 420.0, 297.0),
    ("A2", 594.0, 420.0),
    ("A1", 841.0, 594.0),
    ("A0", 1189.0, 841.0),
)


def select_paper(width_mm: float, height_mm: float) -> str:
    """Return the smallest landscape ISO paper containing the content box."""
    if width_mm <= 0 or height_mm <= 0:
        raise ValueError("paper content dimensions must be positive (fail-closed)")
    for name, long_side, short_side in ISO_PAPER_LANDSCAPE_MM:
        if width_mm <= long_side and height_mm <= short_side:
            return name
    raise ValueError(f"content {width_mm:.2f} mm x {height_mm:.2f} mm exceeds A0 (fail-closed)")


__all__ = ["ISO_PAPER_LANDSCAPE_MM", "select_paper"]
