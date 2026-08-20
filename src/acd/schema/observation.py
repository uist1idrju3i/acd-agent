"""Contracts for non-authoritative ACD observation payloads."""

from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict

from acd.schema.common import AcdModel, NonEmptyStr

ObservationArtifactKind = Literal[
    "agent_settings_observation",
    "conversation_metrics",
    "conversation_stats",
    "event_view_projection",
    "goal_result",
    "hook_rejection_summary",
    "memory_context_observation",
    "model_routing_observation",
    "visual_projection",
    "visual_projection_set",
    "visual_crosscheck_report",
    "visual_vision_observation",
]


class ObservationPayload(AcdModel):
    """Typed envelope for non-authoritative observation payloads."""

    model_config = ConfigDict(extra="allow", frozen=True)

    artifact_kind: ObservationArtifactKind
    pass_evidence: Literal[False] = False
    description: NonEmptyStr | None = None
