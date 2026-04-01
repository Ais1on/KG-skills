from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from ..schemas import SessionCreatePayload
from ..services import create_conversation as svc_create_conversation, list_messages as svc_list_messages, list_sessions_v1 as svc_list_sessions_v1

router = APIRouter()


@router.get("/api/v1/sessions")
def list_sessions_v1(
    query: str = "",
    limit: int = 50,
    offset: int = 0,
    agent_id: str | None = None,
) -> dict[str, Any]:
    rows, total = svc_list_sessions_v1(query, limit, offset, agent_id)
    return {
        "items": rows,
        "total": total,
        "limit": max(1, min(limit, 200)),
        "offset": max(0, offset),
    }


@router.post("/api/v1/sessions")
def create_session_v1(payload: SessionCreatePayload) -> dict[str, Any]:
    resolved_agent_id = (payload.agent_id or "").strip() or "default"
    return svc_create_conversation(resolved_agent_id, payload.title, payload.thread_id)


@router.get("/api/v1/sessions/{session_id}/messages")
def list_session_messages_v1(
    session_id: str,
    limit: int = 200,
    offset: int = 0,
) -> dict[str, Any]:
    rows, total = svc_list_messages(session_id, limit, offset)
    return {
        "items": rows,
        "total": total,
        "limit": max(1, min(limit, 500)),
        "offset": max(0, offset),
    }
