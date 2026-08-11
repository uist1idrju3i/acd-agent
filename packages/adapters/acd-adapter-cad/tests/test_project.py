"""CAD projection determinism and independent output artifacts."""

from __future__ import annotations

import json
from pathlib import Path

from acd_adapter_cad.project import project_enclosure
from acd_core.mechanical import extract_mechanical_lane
from acd_schema.design_graph import DesignGraph

FIXTURE = (
    Path(__file__).resolve().parents[4] / "fixtures" / "golden-design-1" / "graph.json"
)


def test_projection_rerun_uses_normalized_hash_and_skips(tmp_path: Path) -> None:
    graph = DesignGraph.model_validate(json.loads(FIXTURE.read_text()))
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
    assert not first.skipped
    assert second.skipped
    assert first.envelope.output_hash == second.envelope.output_hash
    assert first.step_path.is_file()
    assert first.model_path.is_file()
