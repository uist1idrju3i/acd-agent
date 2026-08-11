"""Projection review request via an SDK LLM.

The LLM (a real one, or ``TestLLM`` in deterministic regressions) proposes
findings; it has no pass/fail authority. Responses that are not a valid JSON
array of ``ReviewFinding`` documents are rejected (fail-closed) instead of
being partially accepted.
"""

from __future__ import annotations

import json
from typing import cast

from openhands.sdk.llm import LLM, Message, TextContent
from pydantic import ValidationError

from acd_schema import ReviewFinding

REVIEW_INSTRUCTION = (
    "Review the following projection and reply with a JSON array of "
    "ReviewFinding documents only."
)


class ReviewResponseError(ValueError):
    """Raised when a review response is not a valid list of findings."""


def request_review_findings(llm: LLM, projection_text: str) -> list[ReviewFinding]:
    messages = [
        Message(role="system", content=[TextContent(text=REVIEW_INSTRUCTION)]),
        Message(role="user", content=[TextContent(text=projection_text)]),
    ]
    # LLM.completion has untyped **kwargs in the SDK; the return type is LLMResponse.
    response = llm.completion(messages)  # pyright: ignore[reportUnknownMemberType]
    parts = [c.text for c in response.message.content if isinstance(c, TextContent)]
    raw = "".join(parts)
    try:
        data = cast(object, json.loads(raw))
    except json.JSONDecodeError as exc:
        raise ReviewResponseError(f"review response is not JSON: {exc}") from exc
    if not isinstance(data, list):
        raise ReviewResponseError("review response is not a JSON array")
    items = cast(list[object], data)
    try:
        return [ReviewFinding.model_validate(item) for item in items]
    except ValidationError as exc:
        raise ReviewResponseError(f"invalid ReviewFinding in response: {exc}") from exc
