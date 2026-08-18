"""Deterministic role-based model routing for the ACD session boundary."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from openhands.sdk.io import FileStore
from openhands.sdk.llm import LLM
from openhands.sdk.llm.message import Message
from openhands.sdk.llm.router import RouterLLM
from pydantic import ValidationError

from acd.openhands.session.observation_store import (
    ObservationPayload,
    write_observation_payload,
)
from acd.schema.common import Sha256, canonical_json_sha256
from acd.schema.model_routing import (
    ModelRoutingBinding,
    ModelRoutingObservation,
    ModelRoutingPolicy,
    ModelRoutingReport,
    RoutingRole,
)


class ModelRoutingError(ValueError):
    """Raised when model routing inputs cannot satisfy the policy contract."""


def model_routing_policy_hash(policy: ModelRoutingPolicy) -> Sha256:
    """Return the canonical hash of a model routing policy."""
    value = policy.model_dump(mode="json")
    value["canonical_hash"] = "unknown"
    return canonical_json_sha256(value)


def load_model_routing_policy(path: Path) -> ModelRoutingPolicy:
    """Load a model routing policy from deterministic JSON."""
    try:
        return ModelRoutingPolicy.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError, ValidationError) as exc:
        raise ModelRoutingError(f"model routing policy is invalid: {path}") from exc


def _binding(policy: ModelRoutingPolicy, role: RoutingRole) -> ModelRoutingBinding:
    for binding in policy.bindings:
        if binding.role == role:
            return binding
    raise ModelRoutingError(f"model routing role is missing: {role}")


def _validate_policy_hash(policy: ModelRoutingPolicy) -> None:
    if policy.canonical_hash != model_routing_policy_hash(policy):
        raise ModelRoutingError("model routing policy canonical hash is invalid")


def _validate_binding(
    policy: ModelRoutingPolicy,
    role: RoutingRole,
    llm: LLM,
    profile: str | None = None,
) -> ModelRoutingBinding:
    _validate_policy_hash(policy)
    binding = _binding(policy, role)
    if llm.model != binding.model:
        raise ModelRoutingError(f"{role} model does not match model routing policy")
    if llm.usage_id != binding.usage_id:
        raise ModelRoutingError(f"{role} usage_id does not match model routing policy")
    if profile is not None and profile != binding.profile:
        raise ModelRoutingError(f"{role} profile does not match model routing policy")
    return binding


def validate_model_routing(
    policy: ModelRoutingPolicy,
    llms: Mapping[RoutingRole, LLM],
    profiles: Mapping[RoutingRole, str] | None = None,
) -> None:
    """Validate the complete role-to-LLM binding against a policy."""
    _validate_policy_hash(policy)
    expected_roles = {binding.role for binding in policy.bindings}
    actual_roles = set(llms)
    if actual_roles != expected_roles:
        raise ModelRoutingError("model routing roles do not match policy")
    for binding in policy.bindings:
        role = binding.role
        _validate_binding(
            policy,
            role,
            llms[role],
            profiles.get(role) if profiles is not None else None,
        )


class FixedRoleRouter(RouterLLM):
    """A RouterLLM that always selects one declared role."""

    role: RoutingRole

    def select_llm(self, messages: list[Message]) -> str:
        """Select the configured role without inspecting message contents."""
        del messages
        if self.role not in self.llms_for_routing:
            raise ModelRoutingError(f"router role is not bound: {self.role}")
        return self.role


def create_fixed_role_router(
    policy: ModelRoutingPolicy,
    role: RoutingRole,
    llm: LLM,
    *,
    profile: str | None = None,
) -> FixedRoleRouter:
    """Create a fixed-role RouterLLM after validating its binding."""
    binding = _validate_binding(policy, role, llm, profile)
    return FixedRoleRouter(
        role=role,
        router_name=f"acd_{role}_router",
        model=binding.model,
        usage_id=binding.usage_id,
        llms_for_routing={role: llm},
    )


def _routing_observations(
    policy: ModelRoutingPolicy,
) -> list[ModelRoutingObservation]:
    return [
        ModelRoutingObservation(
            role=binding.role,
            model=binding.model,
            usage_id=binding.usage_id,
            profile=binding.profile,
        )
        for binding in policy.bindings
    ]


def model_routing_report(
    policy: ModelRoutingPolicy,
    llms: Mapping[RoutingRole, LLM],
    profiles: Mapping[RoutingRole, str] | None = None,
) -> ModelRoutingReport:
    """Build a non-authoritative routing observation report."""
    try:
        validate_model_routing(policy, llms, profiles)
    except ModelRoutingError as exc:
        return ModelRoutingReport(
            status="unknown",
            policy_hash="unknown",
            reason=str(exc),
        )
    return ModelRoutingReport(
        status="pass",
        policy_hash=policy.canonical_hash,
        bindings=_routing_observations(policy),
    )


def model_routing_policy_report(policy: ModelRoutingPolicy) -> ModelRoutingReport:
    """Build a non-authoritative report for a policy without runtime LLMs."""
    try:
        _validate_policy_hash(policy)
    except ModelRoutingError as exc:
        return ModelRoutingReport(
            status="unknown",
            policy_hash="unknown",
            reason=str(exc),
        )
    return ModelRoutingReport(
        status="pass",
        policy_hash=policy.canonical_hash,
        bindings=_routing_observations(policy),
    )


def write_model_routing_report(
    policy: ModelRoutingPolicy,
    llms: Mapping[RoutingRole, LLM],
    path: Path,
    profiles: Mapping[RoutingRole, str] | None = None,
    *,
    file_store: FileStore | None = None,
) -> ModelRoutingReport:
    """Write a deterministic non-authoritative routing observation."""
    report = model_routing_report(policy, llms, profiles)
    payload = ObservationPayload.model_validate(report.model_dump(mode="json"))
    write_observation_payload(
        payload,
        path,
        file_store=file_store,
    )
    return report


def write_model_routing_policy(
    policy: ModelRoutingPolicy,
    path: Path,
) -> ModelRoutingPolicy:
    """Write a policy with its canonical hash populated."""
    value = policy.model_copy(
        update={"canonical_hash": model_routing_policy_hash(policy)}
    )
    path.write_text(
        json.dumps(
            value.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return value
