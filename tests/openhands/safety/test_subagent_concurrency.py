"""Pin how lane parallelism reaches (or does not reach) SDK subagents.

``Agent.tool_concurrency_limit`` is opt-in on the parent agent.  The SDK
``agent_definition_to_factory`` builds subagents from an ``AgentDefinition``
without that field, so every task/delegate subagent serialises its tool calls
regardless of the parent's limit.  These tests fix that observation so a future
SDK bump that starts inheriting the limit is noticed and re-measured.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from openhands.sdk import LLM, Agent
from openhands.sdk.subagent import AgentDefinition, agent_definition_to_factory
from openhands.tools.glob import GlobTool
from openhands.tools.grep import GrepTool
from openhands.tools.preset.default import register_default_tools

from acd.openhands.tools.definitions import register_acd_tools

AGENT_DIR = Path("plugins/acd/agents")


@pytest.fixture(scope="module", autouse=True)
def _tools_registered() -> None:
    register_default_tools(enable_browser=False)
    assert (GlobTool.name, GrepTool.name) == ("glob", "grep")
    register_acd_tools()


@pytest.mark.parametrize("parent_limit", [1, 3])
def test_acd_subagents_do_not_inherit_parent_tool_concurrency(
    parent_limit: int,
) -> None:
    parent = Agent(llm=LLM(model="test"), tools=[], tool_concurrency_limit=parent_limit)
    assert parent.tool_concurrency_limit == parent_limit
    for agent_path in sorted(AGENT_DIR.glob("acd-*.md")):
        definition = AgentDefinition.load(agent_path)
        sub_agent = agent_definition_to_factory(definition)(parent.llm)
        assert sub_agent.tool_concurrency_limit == 1, agent_path.name


def test_acd_agent_definitions_do_not_declare_tool_concurrency() -> None:
    for agent_path in sorted(AGENT_DIR.glob("acd-*.md")):
        definition = AgentDefinition.load(agent_path)
        assert "tool_concurrency_limit" not in definition.metadata, agent_path.name
