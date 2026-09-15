# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "acd @ git+https://github.com/uist1idrju3i/acd-agent@dde03eda4f8825705ebbb8888a81ce8af5f485b5",
# ]
# ///
"""Expose ACD ToolDefinitions through an L3 MCP transport only.

Observations carry no pass authority beyond what the wrapped ACD tool returns.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any, cast

from pydantic import ValidationError

os.environ.setdefault("ACD_REPOSITORY_ROOT", str(Path(__file__).resolve().parents[3]))

from mcp import types
from mcp.server import Server
from mcp.server.lowlevel import NotificationOptions
from mcp.server.models import InitializationOptions
from mcp.server.stdio import stdio_server

from acd.openhands.tools.definitions import ACD_TOOL_DEFINITIONS

logger = logging.getLogger(__name__)


def tool_specs() -> list[tuple[str, Any]]:
    """Build the ordered ACD tool instances exposed by this server."""
    specs: list[tuple[str, Any]] = []
    for name, definition_class in ACD_TOOL_DEFINITIONS:
        definition = cast(Any, definition_class)
        created = definition.create(conv_state=None)
        if len(created) != 1:
            raise ValueError(f"{name} must create exactly one ToolDefinition")
        tool = created[0]
        if tool.name != name:
            raise ValueError(f"{name} created a tool named {tool.name!r}")
        specs.append((name, tool))
    return specs


def _error_result(reason: str, *, fail_closed: bool) -> types.CallToolResult:
    return types.CallToolResult(
        content=[
            types.TextContent(
                type="text",
                text=json.dumps(
                    {
                        "ok": False,
                        "fail_closed": fail_closed,
                        "failure_reason": reason,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            )
        ],
        isError=True,
    )


def call_tool(name: str, arguments: dict[str, Any]) -> types.CallToolResult:
    """Validate and execute one ACD tool without crashing the transport."""
    try:
        tools = dict(tool_specs())
        tool = tools.get(name)
        if tool is None:
            return _error_result(f"unknown ACD tool: {name}", fail_closed=True)
        try:
            action = tool.action_type.model_validate(arguments)
        except ValidationError as exc:
            return _error_result(f"invalid arguments for {name}: {exc}", fail_closed=True)
        observation = tool.as_executable().executor(action)
        return types.CallToolResult(
            content=[
                types.TextContent(
                    type="text",
                    text=observation.model_dump_json(exclude_none=True),
                )
            ],
            isError=not observation.ok,
        )
    except Exception as exc:
        logger.exception("ACD MCP tool %s failed", name)
        return _error_result(str(exc), fail_closed=True)


def _server() -> Server:
    server = Server("acd")

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return mcp_tools()

    @server.call_tool()
    async def handle_call(name: str, arguments: dict[str, Any]) -> types.CallToolResult:
        return call_tool(name, arguments)

    return server


def mcp_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name=name,
            description=tool.description,
            inputSchema=tool.action_type.to_mcp_schema(),
        )
        for name, tool in tool_specs()
    ]


async def _run_server() -> None:
    server = _server()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="acd",
                server_version="0.0.2",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list-tools", action="store_true")
    args = parser.parse_args(argv)
    if args.list_tools:
        print(json.dumps({"tools": sorted(name for name, _ in tool_specs())}))
        return 0
    asyncio.run(_run_server())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
