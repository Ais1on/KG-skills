from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

try:
    from fastapi import HTTPException
except Exception:  # pragma: no cover
    class HTTPException(Exception):
        def __init__(self, status_code: int, detail: str) -> None:
            super().__init__(detail)
            self.status_code = status_code
            self.detail = detail

from ..app_state import AGENT_LOCK, AGENT_STORE, ManagedAgent, WORKSPACE_ROOT
from ..config import AgentConfig, MCPServerConfig
from ..loaders.skill_loader import discover_skills
from .common import now_iso
from .conversation import delete_agent_record, list_agent_records, update_agent_record_name, upsert_agent_record


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
        "redis_url": config.redis_url,
        "redis_key_prefix": config.redis_key_prefix,
        "redis_ttl_seconds": config.redis_ttl_seconds,
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
        redis_url=payload.redis_url,
        redis_key_prefix=payload.redis_key_prefix,
        redis_ttl_seconds=payload.redis_ttl_seconds,
        system_prompt=payload.system_prompt or "",
        dangerous_tools=dangerous_tools,
    )


def dict_to_config(raw: dict[str, Any]) -> AgentConfig:
    class _Payload:
        pass

    payload = _Payload()
    payload.model = str(raw.get("model", "deepseek-chat"))
    payload.api_base = str(raw.get("api_base", "https://api.deepseek.com/v1"))
    payload.api_key_env = str(raw.get("api_key_env", "DEEPSEEK_API_KEY"))
    payload.temperature = float(raw.get("temperature", 0.0))
    payload.skills_dir = str(raw.get("skills_dir", "skills"))
    payload.local_tool_modules = [str(item) for item in raw.get("local_tool_modules", ["kg_agent.builtin_tools"])]
    payload.memory_backend = str(raw.get("memory_backend", "sqlite"))
    payload.memory_path = str(raw.get("memory_path", ".kg_agent/checkpoints.sqlite"))
    payload.redis_url = str(raw.get("redis_url", ""))
    payload.redis_key_prefix = str(raw.get("redis_key_prefix", "kg:langgraph:checkpoint"))
    payload.redis_ttl_seconds = int(raw.get("redis_ttl_seconds", 0))
    payload.system_prompt = str(raw.get("system_prompt", ""))
    payload.dangerous_tools = [str(item) for item in (raw.get("dangerous_tools") or [])]
    payload.mcp_servers = [
        type(
            "MCPPayload",
            (),
            {
                "name": str(item.get("name", "")),
                "transport": str(item.get("transport", "stdio")),
                "command": str(item.get("command", "")),
                "args": [str(arg) for arg in item.get("args", [])],
                "env": {str(k): str(v) for k, v in (item.get("env") or {}).items()},
            },
        )()
        for item in raw.get("mcp_servers", [])
        if isinstance(item, dict)
    ]
    return payload_to_config(payload)


def persist_agent(item: ManagedAgent) -> None:
    upsert_agent_record(
        item.agent_id,
        item.name,
        json.dumps(config_to_dict(item.config), ensure_ascii=False),
        created_at=item.created_at,
    )


async def restore_persisted_agents_async() -> list[str]:
    from ..graph import build_agent_async

    restored: list[str] = []
    records = list_agent_records()
    for row in records:
        try:
            config_raw = json.loads(row["config_json"])
            if not isinstance(config_raw, dict):
                continue
            config = dict_to_config(config_raw)
            runtime = await build_agent_async(config)
            item = ManagedAgent(
                agent_id=row["agent_id"],
                name=row["name"],
                created_at=row["created_at"] or now_iso(),
                config=config,
                runtime=runtime,
            )
            with AGENT_LOCK:
                AGENT_STORE[item.agent_id] = item
            restored.append(item.agent_id)
        except Exception:
            continue
    return restored


def restore_persisted_agents() -> list[str]:
    import asyncio

    return asyncio.run(restore_persisted_agents_async())


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
        update_agent_record_name(agent_id, resolved_name)
        return item


def remove_agent_or_404(agent_id: str) -> ManagedAgent:
    with AGENT_LOCK:
        removed = AGENT_STORE.pop(agent_id, None)
    if removed is None:
        raise HTTPException(status_code=404, detail=f"Agent not found: {agent_id}")
    delete_agent_record(agent_id)
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
