from __future__ import annotations

import asyncio
import json
import time
from typing import Any, AsyncIterator

from langchain_core.messages import HumanMessage

from ..app_state import ManagedAgent


def sse(event: str, payload: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def extract_text_content(value: Any) -> str:
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
        return extract_text_content(text)
    return ""


def extract_tool_calls(chunk: Any) -> list[dict[str, Any]]:
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


def preview(value: Any, max_len: int = 220) -> str:
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


def orchestration_data(status: str, node_name: str, inputs: dict[str, Any] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "status": status,
        "node_name": node_name,
        "timestamp": int(time.time()),
    }
    if inputs:
        payload["inputs"] = inputs
    return payload


def _graph_state(item: ManagedAgent, thread_id: str) -> Any:
    get_state = getattr(item.runtime.graph, "get_state", None)
    if get_state is None:
        return None
    try:
        return get_state(config={"configurable": {"thread_id": thread_id}})
    except Exception:
        return None


def graph_interrupted_on_danger(item: ManagedAgent, thread_id: str) -> bool:
    state = _graph_state(item, thread_id)
    if state is None:
        return False
    nxt = getattr(state, "next", None)
    if isinstance(nxt, (list, tuple, set)):
        return "danger_tools_node" in set(nxt)
    return False


def pending_tool_calls(item: ManagedAgent, thread_id: str) -> list[dict[str, Any]]:
    state = _graph_state(item, thread_id)
    if state is None:
        return []
    values = getattr(state, "values", None)
    if not isinstance(values, dict):
        return []
    messages = values.get("messages")
    if not isinstance(messages, list) or not messages:
        return []
    last = messages[-1]
    calls = getattr(last, "tool_calls", None)
    if not isinstance(calls, list):
        return []

    normalized: list[dict[str, Any]] = []
    for item_call in calls:
        if isinstance(item_call, dict):
            normalized.append(item_call)
        else:
            normalized.append(
                {
                    "name": getattr(item_call, "name", ""),
                    "id": getattr(item_call, "id", ""),
                    "args": getattr(item_call, "args", ""),
                }
            )
    return normalized


async def stream_agent_events(
    item: ManagedAgent,
    message: str,
    thread_id: str,
    *,
    resume: bool = False,
) -> AsyncIterator[dict[str, Any]]:
    graph = item.runtime.graph
    astream_events = getattr(graph, "astream_events", None)

    if astream_events is None:
        if resume:
            return
        answer = await asyncio.to_thread(item.runtime.ask, message, thread_id)
        yield {"event": "token", "data": {"text": answer}}
        yield {"event": "orchestration", "data": orchestration_data("success", "assistant", {"mode": "fallback"})}
        return

    config = {"configurable": {"thread_id": thread_id}}
    if resume:
        payload: Any = None
        try:
            from langgraph.types import Command  # type: ignore

            payload = Command(resume=True)
        except Exception:
            payload = None
    else:
        payload = {"messages": [HumanMessage(content=message)]}

    try:
        stream = astream_events(payload, config=config, version="v2")
    except TypeError:
        stream = astream_events(payload, config=config)

    async for evt in stream:
        event_type = str(evt.get("event", ""))
        name = str(evt.get("name", ""))
        data = evt.get("data") or {}

        if event_type == "on_chain_start" and name in {"assistant", "tools", "danger_tools_node"}:
            phase = "assistant_thinking" if name == "assistant" else "tool_execution"
            yield {"event": "status", "data": {"phase": phase, "node": name}}
            yield {
                "event": "orchestration",
                "data": orchestration_data("running", name, {"input_preview": preview(data.get("input"))}),
            }
            continue

        if event_type == "on_chain_end" and name in {"assistant", "tools", "danger_tools_node"}:
            phase = "assistant_done" if name == "assistant" else "tool_execution_done"
            yield {"event": "status", "data": {"phase": phase, "node": name}}
            yield {
                "event": "orchestration",
                "data": orchestration_data("success", name),
            }
            continue

        if event_type == "on_chain_error" and name in {"assistant", "tools", "danger_tools_node"}:
            yield {
                "event": "orchestration",
                "data": orchestration_data("error", name, {"error": preview(data.get("error"))}),
            }
            continue

        if event_type == "on_tool_start":
            yield {
                "event": "tool",
                "data": {
                    "phase": "start",
                    "tool": name,
                    "input_preview": preview(data.get("input")),
                },
            }
            yield {
                "event": "orchestration",
                "data": orchestration_data("running", name, {"input_preview": preview(data.get("input"))}),
            }
            continue

        if event_type == "on_tool_end":
            yield {
                "event": "tool",
                "data": {
                    "phase": "end",
                    "tool": name,
                    "output_preview": preview(data.get("output")),
                },
            }
            yield {
                "event": "orchestration",
                "data": orchestration_data("success", name, {"output_preview": preview(data.get("output"))}),
            }
            continue

        if event_type == "on_chat_model_stream":
            chunk = data.get("chunk")
            text = extract_text_content(chunk)
            if text:
                yield {"event": "token", "data": {"text": text}}

            for call in extract_tool_calls(chunk):
                call_name = str(call.get("name", "")).strip()
                if call_name:
                    yield {
                        "event": "tool",
                        "data": {
                            "phase": "planned",
                            "tool": call_name,
                            "args_preview": preview(call.get("args", "")),
                        },
                    }
                    yield {
                        "event": "orchestration",
                        "data": orchestration_data(
                            "planned",
                            call_name,
                            {"args_preview": preview(call.get("args", ""))},
                        ),
                    }
