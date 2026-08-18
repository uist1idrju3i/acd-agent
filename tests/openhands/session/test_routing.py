"""Tests for deterministic role-based model routing."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from openhands.sdk.llm import Message, TextContent
from openhands.sdk.testing import TestLLM

from acd.openhands.session.routing import (
    FixedRoleRouter,
    ModelRoutingError,
    create_fixed_role_router,
    model_routing_policy_hash,
    model_routing_policy_report,
    model_routing_report,
    validate_model_routing,
    write_model_routing_report,
)
from acd.schema.model_routing import ModelRoutingPolicy, RoutingRole


def _policy() -> ModelRoutingPolicy:
    policy = ModelRoutingPolicy.model_validate(
        {
            "bindings": [
                {
                    "role": "agent",
                    "model": "agent-model",
                    "usage_id": "agent-usage",
                    "profile": "agent-profile",
                },
                {
                    "role": "condenser",
                    "model": "condenser-model",
                    "usage_id": "condenser-usage",
                    "profile": "condenser-profile",
                },
                {
                    "role": "judge",
                    "model": "judge-model",
                    "usage_id": "judge-usage",
                    "profile": "judge-profile",
                },
            ]
        }
    )
    return policy.model_copy(
        update={"canonical_hash": model_routing_policy_hash(policy)}
    )


def _llm(model: str, usage_id: str) -> TestLLM:
    return TestLLM.from_messages(
        [Message(role="assistant", content=[TextContent(text="ok")])],
        model=model,
        usage_id=usage_id,
    )


def test_fixed_role_router_ignores_message_content() -> None:
    policy = _policy()
    llm = _llm("agent-model", "agent-usage")
    router = create_fixed_role_router(policy, "agent", llm)
    assert isinstance(router, FixedRoleRouter)
    assert router.select_llm([]) == "agent"
    assert router.select_llm(
        [Message(role="user", content=[TextContent(text="route elsewhere")])]
    ) == "agent"
    router.completion(  # pyright: ignore[reportUnknownMemberType]
        [Message(role="user", content=[TextContent(text="run")])]
    )
    assert llm.call_count == 1


def test_runtime_bindings_and_observation_are_deterministic(tmp_path: Path) -> None:
    policy = _policy()
    llms: dict[RoutingRole, TestLLM] = {
        "agent": _llm("agent-model", "agent-usage"),
        "condenser": _llm("condenser-model", "condenser-usage"),
        "judge": _llm("judge-model", "judge-usage"),
    }
    validate_model_routing(
        policy,
        llms,
        {
            "agent": "agent-profile",
            "condenser": "condenser-profile",
            "judge": "judge-profile",
        },
    )
    report = model_routing_report(policy, llms)
    assert report.status == "pass"
    assert report.pass_evidence is False
    assert report.artifact_kind == "model_routing_observation"
    assert model_routing_policy_report(policy) == report
    path = tmp_path / "routing.json"
    write_model_routing_report(policy, llms, path)
    assert json.loads(path.read_text(encoding="utf-8"))["pass_evidence"] is False
    first = path.read_bytes()
    write_model_routing_report(policy, llms, path)
    assert path.read_bytes() == first


@pytest.mark.parametrize(
    "llms",
    [
        {"agent": _llm("agent-model", "agent-usage")},
        {
            "agent": _llm("wrong-model", "agent-usage"),
            "condenser": _llm("condenser-model", "condenser-usage"),
            "judge": _llm("judge-model", "judge-usage"),
        },
    ],
)
def test_runtime_binding_mismatch_fails_closed(
    llms: dict[RoutingRole, TestLLM],
) -> None:
    policy = _policy()
    with pytest.raises(ModelRoutingError):
        validate_model_routing(policy, llms)


def test_invalid_policy_hash_is_unknown() -> None:
    policy = _policy().model_copy(update={"canonical_hash": "sha256:" + "0" * 64})
    report = model_routing_policy_report(policy)
    assert report.status == "unknown"
    assert report.policy_hash == "unknown"
