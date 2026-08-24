import json
from pathlib import Path
from datetime import UTC, datetime
from acd.schema import DesignGraph, RationaleDocument, RationaleRecord, RationaleProvenance
from acd.core.rationale import REQUIRED_RATIONALE_ATTRS, subject_hash_for

def decision_kind(kind: str) -> str:
    mapping = {
        "electrical.board": "stackup",
        "electrical.component": "part_selection",
        "electrical.net": "net_class",
        "firmware.pin_assignment": "firmware_pin",
        "mechanical.outline": "mechanical",
        "fab.order_intent": "fab_process",
        "mechanical.silk_text": "mechanical",
    }
    return mapping.get(kind, "mechanical")

graph = DesignGraph.model_validate_json(Path('fixtures/mini-blink-dongle/graph.json').read_text())
requirement_ids = []
records = []
for node in graph.nodes:
    required = REQUIRED_RATIONALE_ATTRS.get(node.kind, frozenset())
    attrs = sorted(required & set(node.attrs))
    if not attrs:
        continue
    records.append(
        RationaleRecord(
            rationale_id=f"fixture-{node.id}",
            decision_kind=decision_kind(node.kind),
            subject_nodes=[node.id],
            subject_attrs=attrs,
            subject_hash=subject_hash_for(graph, [node.id], attrs),
            decision=f"Use the declared values for {node.id}.",
            justification="Declared by the deterministic design specification.",
            driving_requirements=[],
            driving_requirement_refs=["requirements.json#mbd-req-001"],
            no_alternatives_reason="No alternatives are declared by the specification.",
            provenance=RationaleProvenance(
                source="deterministic_tool",
                recorded_at=datetime(2025, 1, 1, tzinfo=UTC),
            ),
            target_revision=graph.revision,
        )
    )

doc = RationaleDocument(
    graph_id=graph.graph_id,
    revision=graph.revision,
    records=records,
)
Path('fixtures/mini-blink-dongle/rationale.json').write_text(
    json.dumps(doc.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
print(f"Wrote {len(records)} rationale records")
