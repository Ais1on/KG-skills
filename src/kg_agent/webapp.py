from __future__ import annotations

import argparse
import asyncio
import json
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, AsyncIterator

import yaml
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field

from .config import AgentConfig, MCPServerConfig
from .graph import AgentRuntime, build_agent
from .skill_loader import discover_skills


class MCPServerPayload(BaseModel):
    name: str
    transport: str = "stdio"
    command: str = ""
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)


class AgentCreatePayload(BaseModel):
    name: str | None = None
    model: str = "deepseek-chat"
    api_base: str = "https://api.deepseek.com/v1"
    api_key_env: str = "DEEPSEEK_API_KEY"
    temperature: float = 0.0
    skills_dir: str = "skills"
    local_tool_modules: list[str] = Field(default_factory=lambda: ["kg_agent.builtin_tools"])
    mcp_servers: list[MCPServerPayload] = Field(default_factory=list)
    env_file: str = ".env"


class ChatPayload(BaseModel):
    message: str
    thread_id: str = "default"


class SaveConfigPayload(BaseModel):
    path: str


@dataclass(slots=True)
class ManagedAgent:
    agent_id: str
    name: str
    created_at: str
    config: AgentConfig
    runtime: AgentRuntime


APP_ROOT = Path(__file__).resolve().parent
INDEX_HTML = APP_ROOT / "web" / "index.html"
WORKSPACE_ROOT = Path.cwd().resolve()

AGENT_STORE: dict[str, ManagedAgent] = {}
AGENT_LOCK = Lock()

app = FastAPI(title="KG Agent Manager", version="0.2.0")


def _load_dotenv(path: str) -> None:
    if not path:
        return

    dotenv_path = Path(path)
    if not dotenv_path.exists():
        return

    with dotenv_path.open("r", encoding="utf-8") as fp:
        for raw_line in fp:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue

            key, value = line.split("=", 1)
            env_key = key.strip()
            env_value = value.strip()
            if not env_key:
                continue

            if env_value.startswith(("\"", "'")) and env_value.endswith(("\"", "'")) and len(env_value) >= 2:
                env_value = env_value[1:-1]

            os.environ.setdefault(env_key, env_value)


def _config_to_dict(config: AgentConfig) -> dict[str, Any]:
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
    }


def _payload_to_config(payload: AgentCreatePayload) -> AgentConfig:
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

    return AgentConfig(
        model=payload.model,
        api_base=payload.api_base,
        api_key_env=payload.api_key_env,
        temperature=payload.temperature,
        skills_dir=payload.skills_dir,
        local_tool_modules=modules,
        mcp_servers=servers,
    )


def _get_agent_or_404(agent_id: str) -> ManagedAgent:
    with AGENT_LOCK:
        item = AGENT_STORE.get(agent_id)
    if item is None:
        raise HTTPException(status_code=404, detail=f"Agent not found: {agent_id}")
    return item


def _tool_names(runtime: AgentRuntime) -> list[str]:
    names: list[str] = []
    for tool in runtime.tools:
        name = getattr(tool, "name", "")
        if not name:
            name = tool.__class__.__name__
        names.append(str(name))
    return sorted(names)


def _skill_names(config: AgentConfig) -> list[str]:
    return sorted(discover_skills(config.skills_dir).keys())


def _safe_write_path(path_text: str) -> Path:
    target = Path(path_text).expanduser().resolve()
    workspace = WORKSPACE_ROOT

    try:
        common = os.path.commonpath([str(target).lower(), str(workspace).lower()])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"invalid save path: {exc}") from exc

    if common != str(workspace).lower():
        raise HTTPException(status_code=400, detail="path must stay within workspace")

    return target


def _sse(event: str, payload: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _extract_text_content(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text") or item.get("content")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts)
    text = getattr(value, "content", None)
    if isinstance(text, str):
        return text
    if isinstance(text, list):
        return _extract_text_content(text)
    return ""


def _extract_tool_calls(chunk: Any) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    tool_call_chunks = getattr(chunk, "tool_call_chunks", None)
    if isinstance(tool_call_chunks, list):
        for item in tool_call_chunks:
            if isinstance(item, dict):
                calls.append(item)
            else:
                calls.append(
                    {
                        "name": getattr(item, "name", ""),
                        "id": getattr(item, "id", ""),
                        "args": getattr(item, "args", ""),
                    }
                )

    additional_kwargs = getattr(chunk, "additional_kwargs", None)
    if isinstance(additional_kwargs, dict):
        raw_tool_calls = additional_kwargs.get("tool_calls")
        if isinstance(raw_tool_calls, list):
            for item in raw_tool_calls:
                if isinstance(item, dict):
                    fn = item.get("function") if isinstance(item.get("function"), dict) else {}
                    calls.append(
                        {
                            "name": fn.get("name", ""),
                            "id": item.get("id", ""),
                            "args": fn.get("arguments", ""),
                        }
                    )

    return calls


def _preview(value: Any, max_len: int = 220) -> str:
    try:
        if isinstance(value, (dict, list)):
            text = json.dumps(value, ensure_ascii=False)
        else:
            text = str(value)
    except Exception:
        text = repr(value)

    text = text.replace("\n", " ").strip()
    if len(text) > max_len:
        return text[: max_len - 3] + "..."
    return text


async def _stream_agent_events(item: ManagedAgent, message: str, thread_id: str) -> AsyncIterator[str]:
    graph = item.runtime.graph
    astream_events = getattr(graph, "astream_events", None)

    if astream_events is None:
        answer = await asyncio.to_thread(item.runtime.ask, message, thread_id)
        yield _sse("token", {"text": answer})
        return

    payload = {"messages": [HumanMessage(content=message)]}
    config = {"configurable": {"thread_id": thread_id}}

    try:
        stream = astream_events(payload, config=config, version="v2")
    except TypeError:
        stream = astream_events(payload, config=config)

    async for evt in stream:
        event_type = str(evt.get("event", ""))
        name = str(evt.get("name", ""))
        data = evt.get("data") or {}

        if event_type == "on_chain_start" and name in {"assistant", "tools"}:
            phase = "assistant_thinking" if name == "assistant" else "tool_execution"
            yield _sse("status", {"phase": phase, "node": name})
            continue

        if event_type == "on_chain_end" and name in {"assistant", "tools"}:
            phase = "assistant_done" if name == "assistant" else "tool_execution_done"
            yield _sse("status", {"phase": phase, "node": name})
            continue

        if event_type == "on_tool_start":
            tool_input = data.get("input")
            yield _sse(
                "tool",
                {
                    "phase": "start",
                    "tool": name,
                    "input_preview": _preview(tool_input),
                },
            )
            continue

        if event_type == "on_tool_end":
            tool_output = data.get("output")
            yield _sse(
                "tool",
                {
                    "phase": "end",
                    "tool": name,
                    "output_preview": _preview(tool_output),
                },
            )
            continue

        if event_type == "on_chat_model_stream":
            chunk = data.get("chunk")
            text = _extract_text_content(chunk)
            if text:
                yield _sse("token", {"text": text})

            for call in _extract_tool_calls(chunk):
                call_name = str(call.get("name", "")).strip()
                if call_name:
                    yield _sse(
                        "tool",
                        {
                            "phase": "planned",
                            "tool": call_name,
                            "args_preview": _preview(call.get("args", "")),
                        },
                    )


@app.get("/")
def index() -> FileResponse:
    if not INDEX_HTML.exists():
        raise HTTPException(status_code=500, detail="index.html not found")
    return FileResponse(INDEX_HTML)


@app.get("/api/defaults")
def get_defaults() -> dict[str, Any]:
    config = AgentConfig()
    return {
        "config": _config_to_dict(config),
        "skills": _skill_names(config),
        "agents_count": len(AGENT_STORE),
    }


@app.get("/api/skills")
def get_skills(skills_dir: str = "skills") -> dict[str, Any]:
    skill_map = discover_skills(skills_dir)
    records = []
    for item in skill_map.values():
        records.append(
            {
                "name": item.name,
                "display_name": item.display_name,
                "description": item.description,
                "short_description": item.short_description,
                "default_prompt": item.default_prompt,
            }
        )
    records.sort(key=lambda item: item["name"])
    return {"skills_dir": skills_dir, "skills": records, "count": len(records)}


@app.get("/api/agents")
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


@app.post("/api/agents")
def create_agent(payload: AgentCreatePayload) -> dict[str, Any]:
    _load_dotenv(payload.env_file)
    config = _payload_to_config(payload)

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
        created_at=datetime.now(timezone.utc).isoformat(),
        config=config,
        runtime=runtime,
    )

    with AGENT_LOCK:
        AGENT_STORE[agent_id] = item

    return {
        "agent_id": item.agent_id,
        "name": item.name,
        "created_at": item.created_at,
        "config": _config_to_dict(config),
        "tools": _tool_names(runtime),
        "skills": _skill_names(config),
        "warnings": runtime.warnings,
    }


@app.get("/api/agents/{agent_id}")
def get_agent(agent_id: str) -> dict[str, Any]:
    item = _get_agent_or_404(agent_id)
    return {
        "agent_id": item.agent_id,
        "name": item.name,
        "created_at": item.created_at,
        "config": _config_to_dict(item.config),
        "tools": _tool_names(item.runtime),
        "skills": _skill_names(item.config),
        "warnings": item.runtime.warnings,
    }


@app.delete("/api/agents/{agent_id}")
def delete_agent(agent_id: str) -> dict[str, Any]:
    with AGENT_LOCK:
        removed = AGENT_STORE.pop(agent_id, None)
    if removed is None:
        raise HTTPException(status_code=404, detail=f"Agent not found: {agent_id}")
    return {"ok": True, "agent_id": agent_id}


@app.post("/api/agents/{agent_id}/chat")
async def chat(agent_id: str, payload: ChatPayload) -> dict[str, Any]:
    item = _get_agent_or_404(agent_id)
    text = payload.message.strip()
    if not text:
        raise HTTPException(status_code=400, detail="message is required")

    try:
        answer = await asyncio.to_thread(item.runtime.ask, text, payload.thread_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Agent call failed: {exc}") from exc

    return {
        "agent_id": agent_id,
        "thread_id": payload.thread_id,
        "message": text,
        "answer": answer,
    }


@app.get("/api/agents/{agent_id}/chat/stream")
async def chat_stream(agent_id: str, message: str, thread_id: str = "default") -> StreamingResponse:
    item = _get_agent_or_404(agent_id)
    text = message.strip()
    if not text:
        raise HTTPException(status_code=400, detail="message is required")

    async def event_generator() -> AsyncIterator[str]:
        yield _sse("status", {"phase": "request_received", "thread_id": thread_id})
        try:
            async for event_text in _stream_agent_events(item, text, thread_id):
                yield event_text
            yield _sse("done", {"ok": True})
        except Exception as exc:
            yield _sse("error", {"detail": str(exc)})
            yield _sse("done", {"ok": False})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/agents/{agent_id}/save")
def save_agent_config(agent_id: str, payload: SaveConfigPayload) -> dict[str, Any]:
    item = _get_agent_or_404(agent_id)
    target = _safe_write_path(payload.path)
    target.parent.mkdir(parents=True, exist_ok=True)

    data = _config_to_dict(item.config)
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Run FastAPI server for KG Agent Manager")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true")
    parser.add_argument("--env-file", default=".env")
    args = parser.parse_args()

    _load_dotenv(args.env_file)

    import uvicorn

    uvicorn.run("kg_agent.webapp:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
