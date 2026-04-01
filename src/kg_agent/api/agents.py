from __future__ import annotations

import os
import uuid
from typing import Any

import yaml
from fastapi import APIRouter, HTTPException

from ..graph import build_agent
from ..app_state import AGENT_LOCK, AGENT_STORE, ManagedAgent
from ..schemas import AgentCreatePayload, AgentPatchPayload, SaveConfigPayload
from ..services import (
    config_to_dict,
    delete_conversations_by_agent,
    get_agent_or_404,
    load_dotenv,
    now_iso,
    payload_to_config,
    remove_agent_or_404,
    rename_agent,
    safe_write_path,
    skill_names,
    tool_names,
)

router = APIRouter()


@router.get("/api/agents")
def list_agents() -> dict[str, Any]:
    with AGENT_LOCK:
        rows = [
            {
                "agent_id": item.agent_id,
                "name": item.name,
                "created_at": item.created_at,
                "model": item.config.model,
                "api_base": item.config.api_base,
            }
            for item in AGENT_STORE.values()
        ]
    rows.sort(key=lambda item: item["created_at"], reverse=True)
    return {"agents": rows, "count": len(rows)}


@router.post("/api/agents")
def create_agent(payload: AgentCreatePayload) -> dict[str, Any]:
    load_dotenv(payload.env_file)
    config = payload_to_config(payload)

    if not os.environ.get(config.api_key_env, "").strip():
        raise HTTPException(status_code=400, detail=f"Missing API key env: {config.api_key_env}")

    try:
        runtime = build_agent(config)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to build agent: {exc}") from exc

    agent_id = uuid.uuid4().hex[:8]
    resolved_name = (payload.name or "").strip() or f"agent-{agent_id}"

    item = ManagedAgent(
        agent_id=agent_id,
        name=resolved_name,
        created_at=now_iso(),
        config=config,
        runtime=runtime,
    )

    with AGENT_LOCK:
        AGENT_STORE[agent_id] = item

    return {
        "agent_id": item.agent_id,
        "name": item.name,
        "created_at": item.created_at,
        "config": config_to_dict(config),
        "tools": tool_names(runtime),
        "skills": skill_names(config),
        "warnings": runtime.warnings,
    }


@router.get("/api/agents/{agent_id}")
def get_agent(agent_id: str) -> dict[str, Any]:
    item = get_agent_or_404(agent_id)
    return {
        "agent_id": item.agent_id,
        "name": item.name,
        "created_at": item.created_at,
        "config": config_to_dict(item.config),
        "tools": tool_names(item.runtime),
        "skills": skill_names(item.config),
        "warnings": item.runtime.warnings,
    }


@router.patch("/api/agents/{agent_id}")
def patch_agent(agent_id: str, payload: AgentPatchPayload) -> dict[str, Any]:
    item = rename_agent(agent_id, payload.name)
    return {
        "agent_id": item.agent_id,
        "name": item.name,
        "created_at": item.created_at,
    }


@router.delete("/api/agents/{agent_id}")
def delete_agent(agent_id: str, purge_conversations: bool = True) -> dict[str, Any]:
    remove_agent_or_404(agent_id)

    deleted = {"conversations": 0, "messages": 0}
    if purge_conversations:
        deleted = delete_conversations_by_agent(agent_id)

    return {
        "ok": True,
        "agent_id": agent_id,
        "purge_conversations": purge_conversations,
        "deleted": deleted,
    }


@router.post("/api/agents/{agent_id}/save")
def save_agent_config(agent_id: str, payload: SaveConfigPayload) -> dict[str, Any]:
    item = get_agent_or_404(agent_id)
    target = safe_write_path(payload.path)
    target.parent.mkdir(parents=True, exist_ok=True)

    data = config_to_dict(item.config)
    data["mcp_servers"] = {
        row["name"]: {
            "transport": row["transport"],
            "command": row["command"],
            "args": row["args"],
            "env": row["env"],
        }
        for row in data["mcp_servers"]
    }

    target.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return {"ok": True, "path": str(target)}
