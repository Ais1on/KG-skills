from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from ..schemas import ToolConfirmPayload
from ..services import resolve_tool_confirmation

router = APIRouter()


@router.post("/api/v1/tools/confirm")
def confirm_tool(payload: ToolConfirmPayload) -> dict[str, Any]:
    record = resolve_tool_confirmation(payload.confirmation_id, payload.approved)
    return {
        "ok": True,
        "confirmation_id": record.get("id"),
        "status": record.get("status"),
        "approved": bool(record.get("approved")),
        "tool_name": record.get("tool_name"),
        "thread_id": record.get("thread_id"),
    }
