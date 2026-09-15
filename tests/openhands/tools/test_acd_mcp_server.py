"""Tests for the ambient ACD MCP server surface."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

from openhands.sdk.plugin import Plugin

from acd.openhands.tools.ambient import check_ambient_tool_availability
from acd.openhands.tools.definitions import ACD_TOOL_DEFINITIONS

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "plugins" / "acd" / "mcp" / "acd_mcp_server.py"
COMMAND = ROOT / "plugins" / "acd" / "commands" / "vibebb-loop.md"


def _load_module() -> Any:
    spec = importlib.util.spec_from_file_location("acd_mcp_server_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_mcp_tools_match_acd_definitions() -> None:
    module = _load_module()
    specs = module.tool_specs()
    expected = sorted(name for name, _ in ACD_TOOL_DEFINITIONS)
    assert sorted(name for name, _ in specs) == expected
    assert sorted(tool.name for tool in module.mcp_tools()) == expected
    for listed, (_, tool) in zip(module.mcp_tools(), specs, strict=True):
        assert listed.inputSchema == tool.action_type.to_mcp_schema()


def test_plugin_mcp_config_points_to_server_script() -> None:
    plugin = Plugin.load(ROOT / "plugins" / "acd")
    server = plugin.mcp_config["acd"]
    assert server.command == "uv"
    assert server.args is not None
    script_argument = server.args[-1]
    assert isinstance(script_argument, str)
    script_path = Path(script_argument.replace("${SKILL_ROOT}", str(ROOT / "plugins" / "acd")))
    assert script_path.is_file()


def test_unknown_tool_fails_closed() -> None:
    module = _load_module()
    result = module.call_tool("acd_unknown", {})
    payload = json.loads(result.content[0].text)
    assert result.isError is True
    assert payload["fail_closed"] is True
    assert "unknown ACD tool" in payload["failure_reason"]


def test_validate_design_graph_returns_observation() -> None:
    module = _load_module()
    result = module.call_tool(
        "acd_validate_design_graph",
        {"path": str(ROOT / "fixtures" / "golden-design-1" / "graph.json")},
    )
    payload = json.loads(result.content[0].text)
    assert result.isError is False
    assert payload["ok"] is True
    validate_tool = dict(module.tool_specs())["acd_validate_design_graph"]
    assert validate_tool.action_type.model_fields.keys() == {"path"}


def test_invalid_arguments_fail_closed() -> None:
    module = _load_module()
    result = module.call_tool("acd_validate_design_graph", {})
    payload = json.loads(result.content[0].text)
    assert result.isError is True
    assert payload["fail_closed"] is True
    assert "invalid arguments" in payload["failure_reason"]


def test_mcp_names_satisfy_vibebb_allowed_tools() -> None:
    module = _load_module()
    names = [name for name, _ in module.tool_specs()]
    report = check_ambient_tool_availability(COMMAND, names)
    assert report.status == "pass"
    assert report.missing_tools == []
