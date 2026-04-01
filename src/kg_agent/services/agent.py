from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from ..app_state import AGENT_LOCK, AGENT_STORE, ManagedAgent, WORKSPACE_ROOT
from ..config import AgentConfig, MCPServerConfig
from ..loaders.skill_loader import discover_skills


def config_to_dict(config: AgentConfig) -> dict[str, Any]:
    mcp_servers: list[dict[str, Any]] = []
    for name, server in config.mcp_servers.items():
        mcp_servers.append(
            {
                "name": name,
                "transport": server.transport,
                "command": server.command,
                "args": server.args,
                "env": server.env,
            }
        )

    return {
        "model": config.model,
        "api_base": config.api_base,
        "api_key_env": config.api_key_env,
        "temperature": config.temperature,
        "skills_dir": config.skills_dir,
        "local_tool_modules": config.local_tool_modules,
        "mcp_servers": mcp_servers,
        "memory_backend": config.memory_backend,
        "memory_path": config.memory_path,
        "system_prompt": config.system_prompt,
        "dangerous_tools": config.dangerous_tools,
    }


def payload_to_config(payload: Any) -> AgentConfig:
    servers: dict[str, MCPServerConfig] = {}
    for item in payload.mcp_servers:
        name = item.name.strip()
        if not name:
            continue
        servers[name] = MCPServerConfig(
            transport=item.transport,
            command=item.command,
            args=[str(arg) for arg in item.args],
            env={str(k): str(v) for k, v in item.env.items()},
        )

    modules = [item.strip() for item in payload.local_tool_modules if item.strip()]
    if not modules:
        modules = ["kg_agent.builtin_tools"]

    dangerous_tools = [str(item).strip() for item in (payload.dangerous_tools or []) if str(item).strip()]

    return AgentConfig(
        model=payload.model,
        api_base=payload.api_base,
        api_key_env=payload.api_key_env,
        temperature=payload.temperature,
        skills_dir=payload.skills_dir,
        local_tool_modules=modules,
        mcp_servers=servers,
        memory_backend=payload.memory_backend,
        memory_path=payload.memory_path,
        system_prompt=payload.system_prompt or "",
        dangerous_tools=dangerous_tools,
    )


def get_agent_or_404(agent_id: str) -> ManagedAgent:
    with AGENT_LOCK:
        item = AGENT_STORE.get(agent_id)
    if item is None:
        raise HTTPException(status_code=404, detail=f"Agent not found: {agent_id}")
    return item



def rename_agent(agent_id: str, name: str) -> ManagedAgent:
    resolved_name = name.strip()
    if not resolved_name:
        raise HTTPException(status_code=400, detail="name must not be empty")

    with AGENT_LOCK:
        item = AGENT_STORE.get(agent_id)
        if item is None:
            raise HTTPException(status_code=404, detail=f"Agent not found: {agent_id}")
        item.name = resolved_name
        return item


def remove_agent_or_404(agent_id: str) -> ManagedAgent:
    with AGENT_LOCK:
        removed = AGENT_STORE.pop(agent_id, None)
    if removed is None:
        raise HTTPException(status_code=404, detail=f"Agent not found: {agent_id}")
    return removed

def tool_names(runtime: Any) -> list[str]:
    names: list[str] = []
    for tool in runtime.tools:
        name = getattr(tool, "name", "")
        if not name:
            name = tool.__class__.__name__
        names.append(str(name))
    return sorted(names)


def skill_names(config: AgentConfig) -> list[str]:
    return sorted(discover_skills(config.skills_dir).keys())


def safe_write_path(path_text: str) -> Path:
    target = Path(path_text).expanduser().resolve()
    workspace = WORKSPACE_ROOT

    try:
        common = os.path.commonpath([str(target).lower(), str(workspace).lower()])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"invalid save path: {exc}") from exc

    if common != str(workspace).lower():
        raise HTTPException(status_code=400, detail="path must stay within workspace")

    return target
