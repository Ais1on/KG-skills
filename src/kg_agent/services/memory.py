from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any

from fastapi import HTTPException

from ..app_state import CONV_DB_PATH, CONV_LOCK
from .common import now_iso
from .conversation import list_messages


def _session_exists(session_id: str) -> bool:
    with CONV_LOCK:
        conn = sqlite3.connect(CONV_DB_PATH)
        try:
            row = conn.execute("SELECT 1 FROM conversations WHERE id = ?", (session_id,)).fetchone()
            return row is not None
        finally:
            conn.close()


def _build_summary(rows: list[dict[str, Any]]) -> str:
    user_parts: list[str] = []
    assistant_parts: list[str] = []
    for row in rows:
        role = str(row.get("role", ""))
        content = str(row.get("content", "")).strip()
        if not content:
            continue
        if role == "user":
            user_parts.append(content)
        elif role == "assistant":
            assistant_parts.append(content)

    user_focus = "；".join(user_parts[-3:]) if user_parts else "无"
    assistant_focus = "；".join(assistant_parts[-3:]) if assistant_parts else "无"

    lines = [
        "会话摘要",
        f"- 用户关注点: {user_focus[:500]}",
        f"- 已给出结论: {assistant_focus[:500]}",
        f"- 轮次统计: user={len(user_parts)}, assistant={len(assistant_parts)}",
    ]
    return "\n".join(lines)


def create_summary_memory(session_id: str, max_messages: int = 20) -> dict[str, Any]:
    if not _session_exists(session_id):
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    _, total = list_messages(session_id, limit=1, offset=0)
    if total <= 0:
        raise HTTPException(status_code=400, detail="No messages to summarize")

    safe_max = max(1, min(int(max_messages), 200))
    offset = max(0, total - safe_max)
    rows, _ = list_messages(session_id, limit=safe_max, offset=offset)
    content = _build_summary(rows)

    memory_id = uuid.uuid4().hex
    now = now_iso()
    metadata = {
        "source": "auto_summary",
        "message_window": safe_max,
        "message_total": total,
    }

    with CONV_LOCK:
        conn = sqlite3.connect(CONV_DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute(
                """
                INSERT INTO memories (id, session_id, memory_type, content, metadata, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    memory_id,
                    session_id,
                    "summary",
                    content,
                    json.dumps(metadata, ensure_ascii=False),
                    now,
                    now,
                ),
            )
            conn.commit()
        finally:
            conn.close()

    return {
        "id": memory_id,
        "session_id": session_id,
        "memory_type": "summary",
        "content": content,
        "metadata": metadata,
        "created_at": now,
        "updated_at": now,
    }


def list_session_memories(session_id: str, limit: int = 20, offset: int = 0) -> tuple[list[dict[str, Any]], int]:
    if not _session_exists(session_id):
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    safe_limit = max(1, min(int(limit), 200))
    safe_offset = max(0, int(offset))

    with CONV_LOCK:
        conn = sqlite3.connect(CONV_DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            total = conn.execute(
                "SELECT COUNT(*) AS cnt FROM memories WHERE session_id = ?",
                (session_id,),
            ).fetchone()["cnt"]
            rows = conn.execute(
                """
                SELECT *
                FROM memories
                WHERE session_id = ?
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,
                (session_id, safe_limit, safe_offset),
            ).fetchall()
        finally:
            conn.close()

    items: list[dict[str, Any]] = []
    for row in rows:
        try:
            metadata = json.loads(row["metadata"] or "{}")
        except Exception:
            metadata = {}
        if not isinstance(metadata, dict):
            metadata = {}
        items.append(
            {
                "id": row["id"],
                "session_id": row["session_id"],
                "memory_type": row["memory_type"],
                "content": row["content"],
                "metadata": metadata,
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
        )

    return items, int(total)


def create_memory_job(session_id: str, max_messages: int) -> dict[str, Any]:
    if not _session_exists(session_id):
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    job_id = uuid.uuid4().hex
    now = now_iso()
    safe_max = max(1, min(int(max_messages), 200))

    with CONV_LOCK:
        conn = sqlite3.connect(CONV_DB_PATH)
        try:
            conn.execute(
                """
                INSERT INTO memory_jobs (id, session_id, max_messages, status, result, error, created_at, updated_at)
                VALUES (?, ?, ?, 'queued', '{}', '', ?, ?)
                """,
                (job_id, session_id, safe_max, now, now),
            )
            conn.commit()
        finally:
            conn.close()

    return {
        "job_id": job_id,
        "session_id": session_id,
        "max_messages": safe_max,
        "status": "queued",
        "result": None,
        "error": None,
        "created_at": now,
        "updated_at": now,
    }


def _update_memory_job(job_id: str, *, status: str, result: dict[str, Any] | None = None, error: str = "") -> None:
    now = now_iso()
    result_text = json.dumps(result or {}, ensure_ascii=False)
    with CONV_LOCK:
        conn = sqlite3.connect(CONV_DB_PATH)
        try:
            conn.execute(
                """
                UPDATE memory_jobs
                SET status = ?, result = ?, error = ?, updated_at = ?
                WHERE id = ?
                """,
                (status, result_text, error, now, job_id),
            )
            conn.commit()
        finally:
            conn.close()


def run_memory_job(job_id: str) -> None:
    _update_memory_job(job_id, status="running")

    with CONV_LOCK:
        conn = sqlite3.connect(CONV_DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT * FROM memory_jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
        finally:
            conn.close()

    if row is None:
        return

    session_id = str(row["session_id"])
    max_messages = int(row["max_messages"])

    try:
        result = create_summary_memory(session_id, max_messages=max_messages)
        _update_memory_job(job_id, status="done", result=result)
    except Exception as exc:
        _update_memory_job(job_id, status="error", error=str(exc))


def mark_memory_job_error(job_id: str, error: str) -> None:
    _update_memory_job(job_id, status="error", error=error)


def get_memory_job(job_id: str) -> dict[str, Any]:
    with CONV_LOCK:
        conn = sqlite3.connect(CONV_DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT * FROM memory_jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
        finally:
            conn.close()

    if row is None:
        raise HTTPException(status_code=404, detail=f"Memory job not found: {job_id}")

    try:
        result = json.loads(row["result"] or "{}")
    except Exception:
        result = {}
    if not isinstance(result, dict):
        result = {}

    return {
        "job_id": row["id"],
        "session_id": row["session_id"],
        "max_messages": int(row["max_messages"]),
        "status": row["status"],
        "result": result if result else None,
        "error": row["error"] or None,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
