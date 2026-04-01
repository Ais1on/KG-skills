from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from ..schemas import (
    ConversationArchivePayload,
    ConversationCreatePayload,
    ConversationPatchPayload,
    ConversationPinPayload,
)
from ..services import (
    clear_conversation as svc_clear_conversation,
    create_conversation as svc_create_conversation,
    delete_conversation as svc_delete_conversation,
    get_agent_or_404,
    get_conversation_or_404,
    list_conversations as svc_list_conversations,
    list_messages as svc_list_messages,
    update_conversation_flag as svc_update_conversation_flag,
    update_conversation_title as svc_update_conversation_title,
)

router = APIRouter()


@router.post("/api/agents/{agent_id}/conversations")
def create_conversation(agent_id: str, payload: ConversationCreatePayload) -> dict[str, Any]:
    get_agent_or_404(agent_id)
    return svc_create_conversation(agent_id, payload.title, payload.thread_id)


@router.get("/api/agents/{agent_id}/conversations")
def list_conversations(
    agent_id: str,
    query: str = "",
    archived: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    get_agent_or_404(agent_id)
    rows, total = svc_list_conversations(agent_id, query, archived, limit, offset)
    return {
        "items": rows,
        "total": total,
        "limit": max(1, min(limit, 200)),
        "offset": max(0, offset),
    }


@router.get("/api/agents/{agent_id}/conversations/{conversation_id}")
def get_conversation(agent_id: str, conversation_id: str) -> dict[str, Any]:
    get_agent_or_404(agent_id)
    return get_conversation_or_404(agent_id, conversation_id)


@router.get("/api/agents/{agent_id}/conversations/{conversation_id}/messages")
def list_conversation_messages(
    agent_id: str,
    conversation_id: str,
    limit: int = 200,
    offset: int = 0,
) -> dict[str, Any]:
    get_agent_or_404(agent_id)
    get_conversation_or_404(agent_id, conversation_id)
    rows, total = svc_list_messages(conversation_id, limit, offset)
    return {
        "items": rows,
        "total": total,
        "limit": max(1, min(limit, 500)),
        "offset": max(0, offset),
    }


@router.patch("/api/agents/{agent_id}/conversations/{conversation_id}")
def patch_conversation(agent_id: str, conversation_id: str, payload: ConversationPatchPayload) -> dict[str, Any]:
    get_agent_or_404(agent_id)
    return svc_update_conversation_title(agent_id, conversation_id, payload.title)


@router.patch("/api/agents/{agent_id}/conversations/{conversation_id}/pin")
def pin_conversation(agent_id: str, conversation_id: str, payload: ConversationPinPayload) -> dict[str, Any]:
    get_agent_or_404(agent_id)
    return svc_update_conversation_flag(agent_id, conversation_id, "pinned", payload.pinned)


@router.patch("/api/agents/{agent_id}/conversations/{conversation_id}/archive")
def archive_conversation(agent_id: str, conversation_id: str, payload: ConversationArchivePayload) -> dict[str, Any]:
    get_agent_or_404(agent_id)
    return svc_update_conversation_flag(agent_id, conversation_id, "archived", payload.archived)


@router.post("/api/agents/{agent_id}/conversations/{conversation_id}/clear")
def clear_conversation(agent_id: str, conversation_id: str) -> dict[str, Any]:
    get_agent_or_404(agent_id)
    return svc_clear_conversation(agent_id, conversation_id)


@router.delete("/api/agents/{agent_id}/conversations/{conversation_id}")
def delete_conversation(agent_id: str, conversation_id: str) -> dict[str, Any]:
    get_agent_or_404(agent_id)
    svc_delete_conversation(agent_id, conversation_id)
    return {"ok": True, "conversation_id": conversation_id}
