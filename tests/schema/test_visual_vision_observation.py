from __future__ import annotations

from acd.schema import VisualVisionObservation


def test_visual_vision_observation_accepts_legacy_payload_without_tool_event() -> None:
    observation = VisualVisionObservation.model_validate(
        {
            "artifact_kind": "visual_vision_observation",
            "pass_evidence": False,
            "tool_name": "inspect_image_with_vision",
            "profile_name": "vision",
            "model": "model-x",
            "projection_id": "board-png",
            "image_hash": "sha256:" + "a" * 64,
            "response": "legacy observation",
        }
    )

    assert observation.tool_event is None
