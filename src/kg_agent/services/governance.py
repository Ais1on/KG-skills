from __future__ import annotations

import asyncio
import uuid
from typing import Any

from fastapi import HTTPException

from ..app_state import TOOL_CONFIRMATIONS, TOOL_CONFIRM_LOCK
from .common import now_iso

_DANGER_KEYWORDS = (
    "drop",
    "delete",
    "truncate",
    "alter",
    "update_db",
    "execute_sql",
    "send_email",
    "smtp",
    "remove",
    "rm",
)


def is_dangerous_tool(tool_name: str, configured: set[str] | None = None) -> bool:
    name = (tool_name or "").strip().lower()
    if not name:
        return False
    if configured and name in {item.lower() for item in configured}:
        return True
    return any(key in name for key in _DANGER_KEYWORDS)


def create_tool_confirmation(
    *,
    agent_id: str,
    thread_id: str,
    tool_name: str,
    args: dict[str, Any] | None = None,
) -> dict[str, Any]:
    confirmation_id = uuid.uuid4().hex
    record: dict[str, Any] = {
        "id": confirmation_id,
        "agent_id": agent_id,
        "thread_id": thread_id,
        "tool_name": tool_name,
        "args": args or {},
        "status": "pending",
        "approved": None,
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    with TOOL_CONFIRM_LOCK:
        TOOL_CONFIRMATIONS[confirmation_id] = record
    return record


def resolve_tool_confirmation(confirmation_id: str, approved: bool) -> dict[str, Any]:
    with TOOL_CONFIRM_LOCK:
        record = TOOL_CONFIRMATIONS.get(confirmation_id)
        if record is None:
            raise HTTPException(status_code=404, detail=f"confirmation not found: {confirmation_id}")
        if record.get("status") != "pending":
            return record
        record["approved"] = bool(approved)
        record["status"] = "approved" if approved else "rejected"
        record["updated_at"] = now_iso()
        return record


async def wait_for_confirmation(confirmation_id: str, timeout_sec: int = 300) -> dict[str, Any]:
    elapsed = 0.0
    step = 0.5
    while elapsed < timeout_sec:
        with TOOL_CONFIRM_LOCK:
            record = TOOL_CONFIRMATIONS.get(confirmation_id)
            if record is None:
                raise HTTPException(status_code=404, detail=f"confirmation not found: {confirmation_id}")
            if record.get("status") != "pending":
                return record
        await asyncio.sleep(step)
        elapsed += step

    with TOOL_CONFIRM_LOCK:
        record = TOOL_CONFIRMATIONS.get(confirmation_id)
        if record is None:
            raise HTTPException(status_code=404, detail=f"confirmation not found: {confirmation_id}")
        if record.get("status") == "pending":
            record["status"] = "timeout"
            record["approved"] = False
            record["updated_at"] = now_iso()
        return record

