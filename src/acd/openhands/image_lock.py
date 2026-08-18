"""Load and validate the published container image digest lock."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Final

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, field_validator

_DIGEST_PATTERN: Final = re.compile(r"^sha256:[0-9a-f]{64}$")
_PLACEHOLDER_VALUES: Final = {"", "unknown", "tbd", "placeholder", "none", "null"}


def _reject_placeholder(value: str, field_name: str) -> str:
    normalized = value.strip().lower()
    if normalized in _PLACEHOLDER_VALUES:
        raise ValueError(f"{field_name} must be a published value")
    return value


class PublishedImage(BaseModel):
    """A published image and the inputs used to produce it."""

    model_config = ConfigDict(extra="forbid")

    image: str = Field(min_length=1)
    tag: str = Field(min_length=1)
    digest: str
    published_at: datetime
    workflow_run: AnyHttpUrl
    dockerfile: str = Field(min_length=1)
    tools: dict[str, str]

    @field_validator("image")
    @classmethod
    def validate_image(cls, value: str) -> str:
        value = _reject_placeholder(value, "image").strip()
        if "@" in value or ":" in value.rsplit("/", 1)[-1]:
            raise ValueError("image must not include a tag or digest")
        return value

    @field_validator("tag", "dockerfile")
    @classmethod
    def validate_non_placeholder_text(cls, value: str) -> str:
        value = value.strip()
        return _reject_placeholder(value, "image metadata")

    @field_validator("digest")
    @classmethod
    def validate_digest(cls, value: str) -> str:
        value = value.strip()
        if value.lower() in _PLACEHOLDER_VALUES or not _DIGEST_PATTERN.fullmatch(value):
            raise ValueError("digest must be a published sha256 digest")
        if value == "sha256:" + "0" * 64:
            raise ValueError("digest must not be a placeholder digest")
        return value

    @field_validator("tools")
    @classmethod
    def validate_tools(cls, value: dict[str, str]) -> dict[str, str]:
        if not value:
            raise ValueError("tools must contain observed versions")
        for tool_name, version in value.items():
            _reject_placeholder(tool_name.strip(), "tool name")
            if not tool_name.strip():
                raise ValueError("tool names must not be empty")
            _reject_placeholder(version.strip(), f"tool version for {tool_name}")
        return value


class ImageDigestLock(BaseModel):
    """The published image identities used by ACD."""

    model_config = ConfigDict(extra="forbid")

    acd_tools: PublishedImage
    acd_server: PublishedImage | None = None


def load_image_lock(path: Path) -> ImageDigestLock:
    """Load and validate an image lock, preserving parse failures."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid image lock: {path}: {exc}") from exc
    try:
        return ImageDigestLock.model_validate(payload)
    except ValueError as exc:
        raise ValueError(f"invalid image lock: {path}: {exc}") from exc


def pinned_reference(entry: PublishedImage) -> str:
    """Return the immutable image reference for a published entry."""
    return f"{entry.image}@{entry.digest}"
