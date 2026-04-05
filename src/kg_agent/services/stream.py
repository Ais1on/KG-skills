from __future__ import annotations

import asyncio
import json
import threading
import time
from typing import Any, AsyncIterator

from langchain_core.messages import HumanMessage

from ..app_state import ManagedAgent

_TRACEABLE_CHAIN_NODES = {
    "orchestrator",
    "search_gate",
    "text_extraction_skill",
    "assistant",
    "tools",
    "danger_tools_node",
    "sandbox",
    "validator",
    "finalizer",
}


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


def _extract_output_tool_calls(output: Any) -> list[dict[str, Any]]:
    if isinstance(output, dict):
        messages = output.get("messages")
        if isinstance(messages, list) and messages:
            last = messages[-1]
            calls = getattr(last, "tool_calls", None)
            if isinstance(calls, list):
                return [item if isinstance(item, dict) else {"name": getattr(item, "name", ""), "args": getattr(item, "args", ""), "id": getattr(item, "id", "")} for item in calls]
    return []


def _raw_event_to_sse(evt: dict[str, Any]) -> list[dict[str, Any]]:
    event_type = str(evt.get("event", ""))
    name = str(evt.get("name", ""))
    data = evt.get("data") or {}
    rows: list[dict[str, Any]] = []

    if event_type == "on_chain_start" and name in _TRACEABLE_CHAIN_NODES:
        phase_map = {
            "assistant": "assistant_thinking",
            "search_gate": "tool_execution",
            "tools": "tool_execution",
            "danger_tools_node": "tool_execution",
            "orchestrator": "orchestrator_running",
            "text_extraction_skill": "skill_running",
            "sandbox": "sandbox_running",
            "validator": "validator_running",
            "finalizer": "finalizer_running",
        }
        phase = phase_map.get(name, "node_running")
        rows.append({"event": "status", "data": {"phase": phase, "node": name}})
        rows.append(
            {
                "event": "orchestration",
                "data": orchestration_data("running", name, {"input_preview": preview(data.get("input"))}),
            }
        )
        return rows

    if event_type == "on_chain_end" and name in _TRACEABLE_CHAIN_NODES:
        phase_map = {
            "assistant": "assistant_done",
            "search_gate": "tool_execution_done",
            "tools": "tool_execution_done",
            "danger_tools_node": "tool_execution_done",
            "orchestrator": "orchestrator_done",
            "text_extraction_skill": "skill_done",
            "sandbox": "sandbox_done",
            "validator": "validator_done",
            "finalizer": "finalizer_done",
        }
        phase = phase_map.get(name, "node_done")
        rows.append({"event": "status", "data": {"phase": phase, "node": name}})
        rows.append({"event": "orchestration", "data": orchestration_data("success", name)})
        if name == "validator":
            output = data.get("output") if isinstance(data.get("output"), dict) else {}
            entities = output.get("entities") if isinstance(output.get("entities"), list) else []
            triplets = output.get("triplets") if isinstance(output.get("triplets"), list) else []
            rows.append(
                {
                    "event": "graph_data",
                    "data": {
                        "entity_count": len(entities),
                        "triplet_count": len(triplets),
                        "entities": entities[:8],
                        "triplets": triplets[:8],
                    },
                }
            )
        for call in _extract_output_tool_calls(data.get("output")):
            call_name = str(call.get("name", "")).strip()
            if call_name:
                rows.append(
                    {
                        "event": "tool",
                        "data": {
                            "phase": "planned",
                            "tool": call_name,
                            "args_preview": preview(call.get("args", "")),
                        },
                    }
                )
                rows.append(
                    {
                        "event": "orchestration",
                        "data": orchestration_data("planned", call_name, {"args_preview": preview(call.get("args", ""))}),
                    }
                )
        return rows

    if event_type == "on_chain_error" and name in _TRACEABLE_CHAIN_NODES:
        rows.append(
            {
                "event": "orchestration",
                "data": orchestration_data("error", name, {"error": preview(data.get("error"))}),
            }
        )
        return rows

    if event_type == "on_tool_start":
        rows.append(
            {
                "event": "tool",
                "data": {"phase": "start", "tool": name, "input_preview": preview(data.get("input"))},
            }
        )
        rows.append(
            {
                "event": "orchestration",
                "data": orchestration_data("running", name, {"input_preview": preview(data.get("input"))}),
            }
        )
        return rows

    if event_type == "on_tool_end":
        rows.append(
            {
                "event": "tool",
                "data": {"phase": "end", "tool": name, "output_preview": preview(data.get("output"))},
            }
        )
        rows.append(
            {
                "event": "orchestration",
                "data": orchestration_data("success", name, {"output_preview": preview(data.get("output"))}),
            }
        )
        return rows

    if event_type == "on_chat_model_stream":
        chunk = data.get("chunk")
        text = extract_text_content(chunk)
        if text:
            rows.append({"event": "token", "data": {"text": text}})
        for call in extract_tool_calls(chunk):
            call_name = str(call.get("name", "")).strip()
            if call_name:
                rows.append(
                    {
                        "event": "tool",
                        "data": {
                            "phase": "planned",
                            "tool": call_name,
                            "args_preview": preview(call.get("args", "")),
                        },
                    }
                )
                rows.append(
                    {
                        "event": "orchestration",
                        "data": orchestration_data("planned", call_name, {"args_preview": preview(call.get("args", ""))}),
                    }
                )
        return rows

    return rows


def _prefer_sync_stream(item: ManagedAgent) -> bool:
    checkpointer = getattr(item.runtime, "_checkpointer", None)
    if checkpointer is None:
        return False
    module_name = str(getattr(type(checkpointer), "__module__", ""))
    class_name = str(getattr(type(checkpointer), "__name__", ""))
    return module_name.startswith("langgraph.checkpoint.sqlite") and class_name == "SqliteSaver"


async def _stream_sync_graph_events(graph: Any, payload: Any, config: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
    stream_events = getattr(graph, "stream_events", None)
    if not callable(stream_events):
        return

    queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def _producer() -> None:
        try:
            try:
                stream = stream_events(payload, config=config, version="v2")
            except TypeError:
                stream = stream_events(payload, config=config)
            for evt in stream:
                asyncio.run_coroutine_threadsafe(queue.put(("event", evt)), loop).result()
        except Exception as exc:
            asyncio.run_coroutine_threadsafe(queue.put(("error", exc)), loop).result()
        finally:
            asyncio.run_coroutine_threadsafe(queue.put(("done", None)), loop).result()

    threading.Thread(target=_producer, daemon=True).start()

    while True:
        kind, value = await queue.get()
        if kind == "done":
            break
        if kind == "error":
            raise value
        for row in _raw_event_to_sse(value):
            yield row


async def stream_agent_events(
    item: ManagedAgent,
    message: str,
    thread_id: str,
    *,
    resume: bool = False,
) -> AsyncIterator[dict[str, Any]]:
    graph = item.runtime.graph
    astream_events = getattr(graph, "astream_events", None)
    use_sync_stream = _prefer_sync_stream(item)

    if astream_events is None and not use_sync_stream:
        if resume:
            return
        answer = await item.runtime.aask(message, thread_id)
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

    if use_sync_stream:
        async for row in _stream_sync_graph_events(graph, payload, config):
            yield row
        return

    try:
        stream = astream_events(payload, config=config, version="v2")
    except TypeError:
        stream = astream_events(payload, config=config)

    async for evt in stream:
        for row in _raw_event_to_sse(evt):
            yield row
