from __future__ import annotations

import json
from pathlib import Path

from acd.core.feedback import apply_input_feedback
from acd.schema import FeedbackApplyPolicy, FeedbackProposal, FeedbackProposalItem

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "golden-design-1" / "graph.json"


def test_feedback_apply_dry_run_preserves_input_and_writes_l3_record(tmp_path: Path) -> None:
    graph_path = tmp_path / "graph.json"
    graph_path.write_bytes(FIXTURE.read_bytes())
    proposal = FeedbackProposal(
        status="pass",
        graph_id="golden-design-1",
        revision="r1",
        input_hash="sha256:" + "a" * 64,
        output_hash="sha256:" + "b" * 64,
        applicable=True,
        items=[
            FeedbackProposalItem(
                rule_id="rule-1",
                status="proposed",
                node_id="fw.pin.led",
                attr="gpio",
                current_value=7,
                measured_value=8,
                proposed_value=8,
                difference=1,
                evidence_id="evidence.gd1.electrical",
                measurement_name="led_frequency_hz",
                decision_kind="firmware_pin",
                rationale_required=False,
            )
        ],
    )
    policy = FeedbackApplyPolicy(
        graph_id="golden-design-1",
        revision="r1",
        rules=[
            {
                "node_id": "fw.pin.led",
                "attr": "gpio",
                "minimum": 0,
                "maximum": 21,
                "tolerance": 1,
            }
        ],
        input_paths=["graph.json"],
    )
    before = graph_path.read_bytes()
    record = apply_input_feedback(
        proposal,
        policy,
        repository=tmp_path,
        dry_run=True,
        record_path=tmp_path / "record.json",
    )

    assert graph_path.read_bytes() == before
    assert record["record_class"] == "L3"
    assert record["pass_evidence"] is False
    assert json.loads((tmp_path / "record.json").read_text())["dry_run"] is True
