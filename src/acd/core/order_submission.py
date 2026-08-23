"""Provider boundary for real order submission."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol

from acd.schema.common import Sha256, canonical_json_sha256


class OrderSubmissionProvider(Protocol):
    provider_id: str

    def submit(self, payload: dict[str, object], credential: str) -> dict[str, object]: ...


@dataclass(frozen=True)
class OrderSubmissionRecord:
    provider_id: str
    target_revision: str
    package_hash: Sha256
    destination: str
    pass_evidence: bool = False
    record_class: str = "L3"

    def as_dict(self) -> dict[str, object]:
        value: dict[str, object] = {
            "record_class": self.record_class,
            "pass_evidence": self.pass_evidence,
            "provider_id": self.provider_id,
            "target_revision": self.target_revision,
            "package_hash": self.package_hash,
            "destination": self.destination,
        }
        value["content_sha256"] = canonical_json_sha256(value)
        return value


class DeclaredProviderUnavailable(ValueError):
    """Raised because real supplier adapters are intentionally not bundled."""


def resolve_order_provider(configuration: dict[str, object]) -> str:
    provider = configuration.get("provider")
    if not isinstance(provider, str) or not provider:
        raise DeclaredProviderUnavailable("no order provider is configured")
    if provider != "boundary":
        raise DeclaredProviderUnavailable(f"unknown order provider: {provider}")
    credential_env = configuration.get("credential_env")
    if not isinstance(credential_env, str) or not credential_env:
        raise DeclaredProviderUnavailable("order provider credential environment is missing")
    if not os.environ.get(credential_env):
        raise DeclaredProviderUnavailable(
            f"order provider credential is unavailable: {credential_env}"
        )
    return provider


def build_order_submission_record(
    *,
    provider_id: str,
    target_revision: str,
    package_hash: Sha256,
    destination: str,
) -> dict[str, object]:
    return OrderSubmissionRecord(
        provider_id=provider_id,
        target_revision=target_revision,
        package_hash=package_hash,
        destination=destination,
    ).as_dict()


__all__ = [
    "DeclaredProviderUnavailable",
    "OrderSubmissionProvider",
    "OrderSubmissionRecord",
    "build_order_submission_record",
    "resolve_order_provider",
]
