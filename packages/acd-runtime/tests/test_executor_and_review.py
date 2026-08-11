"""Envelope enforcement and the deterministic TestLLM review regression."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from openhands.sdk.llm import Message, TextContent
from openhands.sdk.testing import TestLLM

from acd_runtime import (
    ReviewResponseError,
    request_review_findings,
    run_enveloped,
    sha256_of,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
FINDING_FIXTURE = REPO_ROOT / "fixtures" / "contracts" / "valid" / "review-finding.json"


def test_run_enveloped_records_hashes_and_unknown_config() -> None:
    output, envelope = run_enveloped(
        tool_name="stub-tool",
        tool_version="1.0.0",
        format_version="1",
        config=None,
        input_data=b"netlist",
        target_revision="r3",
        execution_env="test",
        measurement_conditions="unit test",
        runner=lambda data: (data.upper(), 0, "not_applicable"),
    )
    assert output == b"NETLIST"
    assert envelope.input_hash == sha256_of(b"netlist")
    assert envelope.output_hash == sha256_of(b"NETLIST")
    assert envelope.config_hash == "unknown"
    assert envelope.has_unknown()  # unknown config keeps this out of pass verdicts

    _, pinned = run_enveloped(
        tool_name="stub-tool",
        tool_version="1.0.0",
        format_version="1",
        config=b"cfg",
        input_data=b"netlist",
        target_revision="r3",
        execution_env="test",
        measurement_conditions="unit test",
        runner=lambda data: (data, 0, "not_applicable"),
    )
    assert not pinned.has_unknown()


def _assistant(text: str) -> Message:
    return Message(role="assistant", content=[TextContent(text=text)])


def test_testllm_review_regression_is_deterministic() -> None:
    finding = json.loads(FINDING_FIXTURE.read_text(encoding="utf-8"))
    llm = TestLLM.from_messages([_assistant(json.dumps([finding]))])
    findings = request_review_findings(llm, "projection: golden-led-board r3")
    assert len(findings) == 1
    assert findings[0].finding_id == finding["finding_id"]
    assert findings[0].review_view == "RV1"


def test_review_rejects_non_json_and_invalid_findings() -> None:
    llm = TestLLM.from_messages(
        [
            _assistant("looks good to me!"),
            _assistant(json.dumps({"not": "a list"})),
            _assistant(json.dumps([{"finding_id": "x"}])),
        ]
    )
    with pytest.raises(ReviewResponseError, match="not JSON"):
        request_review_findings(llm, "projection")
    with pytest.raises(ReviewResponseError, match="not a JSON array"):
        request_review_findings(llm, "projection")
    with pytest.raises(ReviewResponseError, match="invalid ReviewFinding"):
        request_review_findings(llm, "projection")
