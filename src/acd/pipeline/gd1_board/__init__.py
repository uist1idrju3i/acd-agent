"""GD1 board pipeline package.

`acd.pipeline.gd1_board` keeps its historical import surface (`run_pipeline`, `main`,
`placements_from_graph`, `build_electrical_evidence`) while the stages live in
sibling modules: `routing`, `width_control`, `measurement`, `fabrication`,
`visual_stages`, `evidence`, and `manifest`.
"""

from __future__ import annotations

from .evidence import build_electrical_evidence
from .measurement import GERBER_LAYERS
from .pipeline import main, placements_from_graph, run_pipeline

__all__ = [
    "GERBER_LAYERS",
    "build_electrical_evidence",
    "main",
    "placements_from_graph",
    "run_pipeline",
]
