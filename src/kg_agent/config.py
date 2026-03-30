from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass(slots=True)
class MCPServerConfig:
    transport: str = "stdio"
    command: str = ""
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class AgentConfig:
    model: str = "deepseek-chat"
    api_base: str = "https://api.deepseek.com/v1"
    api_key_env: str = "DEEPSEEK_API_KEY"
    temperature: float = 0.0
    skills_dir: str = "skills"
    local_tool_modules: list[str] = field(default_factory=lambda: ["kg_agent.builtin_tools"])
    mcp_servers: dict[str, MCPServerConfig] = field(default_factory=dict)


def _to_mcp_server_config(value: Any) -> MCPServerConfig:
    if isinstance(value, MCPServerConfig):
        return value
    if not isinstance(value, dict):
        raise ValueError(f"Invalid MCP server config: {value!r}")
    return MCPServerConfig(
        transport=str(value.get("transport", "stdio")),
        command=str(value.get("command", "")),
        args=[str(item) for item in value.get("args", [])],
        env={str(k): str(v) for k, v in value.get("env", {}).items()},
    )


def load_config(path: str | Path | None = None) -> AgentConfig:
    if path is None:
        return AgentConfig()

    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}

    model = str(raw.get("model", "deepseek-chat"))
    api_base = str(raw.get("api_base", "https://api.deepseek.com/v1"))
    api_key_env = str(raw.get("api_key_env", "DEEPSEEK_API_KEY"))
    temperature = float(raw.get("temperature", 0.0))
    skills_dir = str(raw.get("skills_dir", "skills"))
    local_tool_modules = [str(item) for item in raw.get("local_tool_modules", ["kg_agent.builtin_tools"])]

    servers: dict[str, MCPServerConfig] = {}
    for server_name, server_conf in (raw.get("mcp_servers") or {}).items():
        servers[str(server_name)] = _to_mcp_server_config(server_conf)

    return AgentConfig(
        model=model,
        api_base=api_base,
        api_key_env=api_key_env,
        temperature=temperature,
        skills_dir=skills_dir,
        local_tool_modules=local_tool_modules,
        mcp_servers=servers,
    )
