"""CAD projection determinism and independent output artifacts."""

from __future__ import annotations

import json
from pathlib import Path

from acd.adapters.cad.project import project_enclosure
from acd.core.mechanical import extract_mechanical_lane
from acd.schema.design_graph import DesignGraph

FIXTURE = (
    Path(__file__).resolve().parents[3] / "fixtures" / "golden-design-1" / "graph.json"
)


def test_projection_rerun_matches_normalized_hash(tmp_path: Path) -> None:
    graph = DesignGraph.model_validate(json.loads(FIXTURE.read_text(encoding="utf-8")))
    lane = extract_mechanical_lane(graph)
    first = project_enclosure(
        lane,
        graph_path=FIXTURE,
        out_dir=tmp_path,
        target_revision=graph.revision,
    )
    second = project_enclosure(
        lane,
        graph_path=FIXTURE,
        out_dir=tmp_path,
        target_revision=graph.revision,
    )
    assert first.envelope.output_hash == second.envelope.output_hash
    assert first.step_path.is_file()
    assert first.model_path.is_file()
