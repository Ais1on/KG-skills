from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass, field
from typing import Any

from langchain_core.tools import BaseTool

from .config import MCPServerConfig


@dataclass(slots=True)
class MCPLoadResult:
    tools: list[BaseTool] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    clients: list[Any] = field(default_factory=list)


def _run_awaitable(value: Any):
    if not inspect.isawaitable(value):
        return value
    return asyncio.run(value)


def load_mcp_tools(mcp_servers: dict[str, MCPServerConfig]) -> MCPLoadResult:
    result = MCPLoadResult()

    if not mcp_servers:
        return result

    try:
        from langchain_mcp_adapters.client import MultiServerMCPClient
    except ImportError:
        result.warnings.append(
            "MCP servers configured but langchain-mcp-adapters is not installed. "
            "Install with: pip install .[mcp]"
        )
        return result

    server_conf: dict[str, dict[str, Any]] = {}
    for name, conf in mcp_servers.items():
        if not conf.command:
            result.warnings.append(f"MCP server '{name}' skipped because command is empty.")
            continue
        server_conf[name] = {
            "transport": conf.transport,
            "command": conf.command,
            "args": conf.args,
            "env": conf.env,
        }

    if not server_conf:
        return result

    try:
        client = MultiServerMCPClient(server_conf)
        get_tools_fn = getattr(client, "get_tools", None)
        if get_tools_fn is None:
            result.warnings.append("MCP client does not expose get_tools().")
            return result

        mcp_tools = _run_awaitable(get_tools_fn())
        if mcp_tools is None:
            result.warnings.append("MCP client returned no tools.")
            return result

        result.tools.extend(list(mcp_tools))
        result.clients.append(client)
    except Exception as exc:  # pragma: no cover
        result.warnings.append(f"Failed to load MCP tools: {exc}")

    return result
