"""SDK-independent helpers for deterministic order-execution payloads."""

from __future__ import annotations

from acd.schema import DryRunOrderPayload, PreOrderGateRecord
from acd.schema.common import NonEmptyStr, Sha256


def build_dry_run_order_payload(
    *,
    authorization: PreOrderGateRecord,
    package_hash: Sha256,
    destination: NonEmptyStr,
) -> DryRunOrderPayload:
    """Build the stable payload shown by a dry-run without side effects."""
    return DryRunOrderPayload(
        authorization_hash=authorization.authorization_hash,
        target_revision=authorization.target_revision,
        package_hash=package_hash,
        destination=destination,
        total=authorization.total,
    )


__all__ = ["build_dry_run_order_payload"]
