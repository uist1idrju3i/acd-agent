"""Contracts for non-authoritative ACD observation payloads."""

from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict

from acd.schema.common import AcdModel, NonEmptyStr

ObservationArtifactKind = Literal[
    "agent_settings_observation",
    "conversation_metrics",
    "conversation_stats",
    "goal_result",
    "model_routing_observation",
]


class ObservationPayload(AcdModel):
    """Typed envelope for non-authoritative observation payloads."""

    model_config = ConfigDict(extra="allow", frozen=True)

    artifact_kind: ObservationArtifactKind
    pass_evidence: Literal[False] = False
    description: NonEmptyStr | None = None
