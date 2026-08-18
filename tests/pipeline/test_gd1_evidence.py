"""GD1 electrical Evidence construction tests."""

# pyright: reportMissingTypeStubs=false

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

import pytest

from acd.pipeline.gd1_board import build_electrical_evidence
from acd.schema.evidence import Evidence
from acd.schema.tool_envelope import ToolEnvelope


def _envelope(
    context: Literal["container", "host", "unknown"] = "host",
    digest: str | None = None,
) -> ToolEnvelope:
    return ToolEnvelope(
        tool_name="kicad-cli",
        tool_version="10.0.5",
        format_version="json",
        config_hash="sha256:" + "a" * 64,
        input_hash="sha256:" + "b" * 64,
        output_hash="sha256:" + "c" * 64,
        execution_env=f"linux-x86_64; container={digest or 'none'}",
        execution_context=context,
        container_image_digest=digest,
        measurement_conditions="test",
        convergence_state="converged",
        target_revision="r3",
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
        exit_code=0,
    )


def _build(envelope: ToolEnvelope) -> Evidence:
    return build_electrical_evidence(
        revision="r3",
        envelope=envelope,
        erc_errors=0,
        erc_unconnected=0,
        routing_converged=True,
        drc_errors=0,
        drc_unconnected=0,
        silkscreen_status="measured_pass",
        dfm_status="pass",
        order_readiness_status="ready",
    )


def test_electrical_evidence_is_provisional_on_host() -> None:
    evidence = _build(_envelope())
    assert evidence.is_provisional()
    assert not evidence.supports_authoritative_pass("r3")


def test_missing_gate_value_fails_closed() -> None:
    with pytest.raises(ValueError, match="unknown"):
        build_electrical_evidence(
            revision="r3",
            envelope=_envelope(),
            erc_errors=0,
            erc_unconnected=0,
            routing_converged=True,
            drc_errors=0,
            drc_unconnected=0,
            silkscreen_status=None,
            dfm_status="pass",
            order_readiness_status="ready",
        )
