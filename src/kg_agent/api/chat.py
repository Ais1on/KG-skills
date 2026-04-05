from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from ..schemas import ChatPayload
from ..services import (
    conversation_record_turn,
    create_tool_confirmation,
    get_agent_or_404,
    get_conversation_or_404,
    graph_interrupted_on_danger,
    is_dangerous_tool,
    pending_tool_calls,
    sse,
    stream_agent_events,
    wait_for_confirmation,
)

router = APIRouter()


@router.post("/api/agents/{agent_id}/chat")
async def chat(agent_id: str, payload: ChatPayload) -> dict[str, Any]:
    item = get_agent_or_404(agent_id)
    text = payload.message.strip()
    if not text:
        raise HTTPException(status_code=400, detail="message is required")

    conversation: dict[str, Any] | None = None
    if payload.conversation_id:
        conversation = get_conversation_or_404(agent_id, payload.conversation_id)
        thread_id = conversation["thread_id"]
    else:
        thread_id = payload.thread_id or "default"

    try:
        answer = await item.runtime.aask(text, thread_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Agent call failed: {exc}") from exc

    if conversation is not None:
        conversation_record_turn(conversation["id"], text, answer)

    return {
        "agent_id": agent_id,
        "conversation_id": conversation["id"] if conversation else None,
        "thread_id": thread_id,
        "message": text,
        "answer": answer,
    }


@router.post("/api/agents/{agent_id}/chat/stream")
async def chat_stream(
    agent_id: str,
    payload: ChatPayload,
) -> StreamingResponse:
    item = get_agent_or_404(agent_id)
    text = payload.message.strip()
    if not text:
        raise HTTPException(status_code=400, detail="message is required")

    conversation: dict[str, Any] | None = None
    resolved_thread_id = payload.thread_id or "default"
    if payload.conversation_id:
        conversation = get_conversation_or_404(agent_id, payload.conversation_id)
        resolved_thread_id = conversation["thread_id"]

    async def event_generator() -> AsyncIterator[str]:
        assistant_parts: list[str] = []
        yield sse("status", {"phase": "request_received", "thread_id": resolved_thread_id})
        try:
            resume = False
            while True:
                async for event in stream_agent_events(item, text, resolved_thread_id, resume=resume):
                    event_name = str(event.get("event", ""))
                    event_data = event.get("data") if isinstance(event.get("data"), dict) else {}
                    if event_name == "token":
                        assistant_parts.append(str(event_data.get("text", "")))
                    yield sse(event_name, event_data)

                if not graph_interrupted_on_danger(item, resolved_thread_id):
                    break

                calls = pending_tool_calls(item, resolved_thread_id)
                danger_calls = [
                    call
                    for call in calls
                    if is_dangerous_tool(str(call.get("name", "")), item.runtime.dangerous_tools)
                ]
                target = danger_calls[0] if danger_calls else (calls[0] if calls else {"name": "danger_tools_node", "args": {}})
                tool_name = str(target.get("name", "danger_tools_node"))

                confirm = create_tool_confirmation(
                    agent_id=agent_id,
                    thread_id=resolved_thread_id,
                    tool_name=tool_name,
                    args={"tool_calls": calls},
                )
                yield sse(
                    "tool_confirm_required",
                    {
                        "confirmation_id": confirm["id"],
                        "tool_name": tool_name,
                        "args": confirm.get("args", {}),
                        "thread_id": resolved_thread_id,
                    },
                )

                decision = await wait_for_confirmation(confirm["id"])
                if not bool(decision.get("approved")):
                    yield sse("error", {"detail": f"tool denied: {tool_name}"})
                    yield sse("done", {"ok": False})
                    return

                resume = True

            if conversation is not None:
                conversation_record_turn(conversation["id"], text, "".join(assistant_parts))

            yield sse("done", {"ok": True})
        except Exception as exc:
            if conversation is not None and assistant_parts:
                conversation_record_turn(conversation["id"], text, "".join(assistant_parts))
            yield sse("error", {"detail": str(exc)})
            yield sse("done", {"ok": False})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
