from __future__ import annotations

import os
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException

from ..app_state import AGENT_LOCK, AGENT_STORE, ManagedAgent
from ..config import AgentConfig, MCPServerConfig
from ..graph import build_agent
from ..schemas import AgentFromTemplatePayload
from ..services import (
    config_to_dict,
    create_conversation,
    get_template_or_404,
    list_templates,
    load_dotenv,
    now_iso,
    skill_names,
    tool_names,
)

router = APIRouter()


def _template_to_config(template: dict[str, Any]) -> AgentConfig:
    model_config = template.get("model_config") if isinstance(template.get("model_config"), dict) else {}
    tools_config = template.get("tools_config") if isinstance(template.get("tools_config"), dict) else {}

    mcp_servers_raw = model_config.get("mcp_servers") if isinstance(model_config.get("mcp_servers"), dict) else {}
    servers: dict[str, MCPServerConfig] = {}
    for name, conf in mcp_servers_raw.items():
        if not isinstance(conf, dict):
            continue
        servers[str(name)] = MCPServerConfig(
            transport=str(conf.get("transport", "stdio")),
            command=str(conf.get("command", "")),
            args=[str(x) for x in conf.get("args", [])],
            env={str(k): str(v) for k, v in (conf.get("env") or {}).items()},
        )

    dangerous = [str(x).strip() for x in tools_config.get("dangerous_tools", []) if str(x).strip()]

    return AgentConfig(
        model=str(model_config.get("model", "deepseek-chat")),
        api_base=str(model_config.get("api_base", "https://api.deepseek.com/v1")),
        api_key_env=str(model_config.get("api_key_env", "DEEPSEEK_API_KEY")),
        temperature=float(model_config.get("temperature", 0.0)),
        skills_dir=str(model_config.get("skills_dir", "skills")),
        local_tool_modules=[str(x) for x in model_config.get("local_tool_modules", ["kg_agent.builtin_tools"])],
        mcp_servers=servers,
        memory_backend=str(model_config.get("memory_backend", "sqlite")),
        memory_path=str(model_config.get("memory_path", ".kg_agent/checkpoints.sqlite")),
        system_prompt=str(template.get("system_prompt", "")),
        dangerous_tools=dangerous,
    )


@router.get("/api/v1/templates")
def get_templates(limit: int = 100, offset: int = 0) -> dict[str, Any]:
    items, total = list_templates(limit=limit, offset=offset)
    return {
        "items": items,
        "total": total,
        "limit": max(1, min(limit, 200)),
        "offset": max(0, offset),
    }


@router.post("/api/v1/agents/from-template")
def create_agent_from_template(payload: AgentFromTemplatePayload) -> dict[str, Any]:
    load_dotenv(payload.env_file)
    template = get_template_or_404(payload.template_id)
    config = _template_to_config(template)

    if not os.environ.get(config.api_key_env, "").strip():
        raise HTTPException(status_code=400, detail=f"Missing API key env: {config.api_key_env}")

    try:
        runtime = build_agent(config)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to build agent from template: {exc}") from exc

    agent_id = uuid.uuid4().hex[:8]
    resolved_name = (payload.agent_name or "").strip() or f"agent-{agent_id}"
    agent = ManagedAgent(
        agent_id=agent_id,
        name=resolved_name,
        created_at=now_iso(),
        config=config,
        runtime=runtime,
    )

    with AGENT_LOCK:
        AGENT_STORE[agent_id] = agent

    session = create_conversation(agent_id, payload.session_title, None)

    return {
        "template": template,
        "agent": {
            "agent_id": agent.agent_id,
            "name": agent.name,
            "created_at": agent.created_at,
            "config": config_to_dict(config),
            "tools": tool_names(runtime),
            "skills": skill_names(config),
            "warnings": runtime.warnings,
        },
        "session": session,
    }
