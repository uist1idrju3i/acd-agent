"""Allowlisted, lazy secret configuration for ACD conversations."""

from __future__ import annotations

import os

from openhands.sdk.secret import SecretSource, SecretValue
from pydantic import Field

ACD_SECRET_ENV_VARS: tuple[str, ...] = (
    "ACD_API_KEY",
    "ANTHROPIC_API_KEY",
    "GITHUB_TOKEN",
    "LLM_API_KEY",
    "OPENAI_API_KEY",
)


class EnvironmentSecret(SecretSource):
    """Resolve one allowlisted environment variable only when requested."""

    environment_name: str = Field(...)

    def get_value(self) -> str:
        return os.environ.get(self.environment_name, "")


def build_acd_secret_mapping() -> dict[str, SecretValue]:
    """Return lazy sources for explicitly allowlisted environment variables."""
    return {
        name: EnvironmentSecret(environment_name=name)
        for name in ACD_SECRET_ENV_VARS
        if name in os.environ
    }
