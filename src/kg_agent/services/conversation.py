from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any

from fastapi import HTTPException

from ..app_state import CONV_DB_PATH, CONV_LOCK
from .common import now_iso


def init_conversation_db() -> None:
    CONV_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CONV_LOCK:
        conn = sqlite3.connect(CONV_DB_PATH)
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY,
                    agent_id TEXT NOT NULL,
                    thread_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    pinned INTEGER NOT NULL DEFAULT 0,
                    archived INTEGER NOT NULL DEFAULT 0,
                    message_count INTEGER NOT NULL DEFAULT 0,
                    last_message_preview TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_active_at TEXT NOT NULL,
                    UNIQUE(agent_id, thread_id)
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_conv_agent ON conversations(agent_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_conv_agent_active ON conversations(agent_id, last_active_at)")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    tool_calls TEXT NOT NULL DEFAULT '[]',
                    metadata TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_msg_session_created ON messages(session_id, created_at)")

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    memory_type TEXT NOT NULL,
                    content TEXT NOT NULL,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_mem_session_created ON memories(session_id, created_at)")

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_jobs (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    max_messages INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    result TEXT NOT NULL DEFAULT '{}',
                    error TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_memory_jobs_created ON memory_jobs(created_at)")

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_templates (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    system_prompt TEXT NOT NULL DEFAULT '',
                    model_config TEXT NOT NULL DEFAULT '{}',
                    tools_config TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_tpl_name ON agent_templates(name)")

            # Seed one default template for M2 bootstrap.
            exists = conn.execute("SELECT 1 FROM agent_templates LIMIT 1").fetchone()
            if exists is None:
                now = now_iso()
                conn.execute(
                    """
                    INSERT INTO agent_templates (
                        id, name, system_prompt, model_config, tools_config, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "tpl-default",
                        "Default Assistant",
                        "You are a concise and reliable AI assistant.",
                        json.dumps({
                            "model": "deepseek-chat",
                            "api_base": "https://api.deepseek.com/v1",
                            "api_key_env": "DEEPSEEK_API_KEY",
                            "temperature": 0.0,
                            "skills_dir": "skills",
                            "local_tool_modules": ["kg_agent.builtin_tools"],
                            "memory_backend": "sqlite",
                            "memory_path": ".kg_agent/checkpoints.sqlite",
                        }, ensure_ascii=False),
                        json.dumps({"dangerous_tools": []}, ensure_ascii=False),
                        now,
                        now,
                    ),
                )
            conn.commit()
        finally:
            conn.close()


def conv_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "agent_id": row["agent_id"],
        "thread_id": row["thread_id"],
        "title": row["title"],
        "pinned": bool(row["pinned"]),
        "archived": bool(row["archived"]),
        "message_count": int(row["message_count"]),
        "last_message_preview": row["last_message_preview"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "last_active_at": row["last_active_at"],
    }


def create_conversation(agent_id: str, title: str | None, thread_id: str | None) -> dict[str, Any]:
    now = now_iso()
    conv_id = uuid.uuid4().hex
    resolved_thread_id = (thread_id or "").strip() or f"thread-{uuid.uuid4().hex[:12]}"
    resolved_title = (title or "").strip() or "新会话"

    with CONV_LOCK:
        conn = sqlite3.connect(CONV_DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            try:
                conn.execute(
                    """
                    INSERT INTO conversations (
                        id, agent_id, thread_id, title,
                        pinned, archived, message_count, last_message_preview,
                        created_at, updated_at, last_active_at
                    ) VALUES (?, ?, ?, ?, 0, 0, 0, '', ?, ?, ?)
                    """,
                    (conv_id, agent_id, resolved_thread_id, resolved_title, now, now, now),
                )
                conn.commit()
            except sqlite3.IntegrityError as exc:
                raise HTTPException(status_code=409, detail=f"thread_id already exists for this agent: {resolved_thread_id}") from exc

            row = conn.execute("SELECT * FROM conversations WHERE id = ?", (conv_id,)).fetchone()
            if row is None:
                raise HTTPException(status_code=500, detail="failed to create conversation")
            return conv_row_to_dict(row)
        finally:
            conn.close()


def get_conversation_or_404(agent_id: str, conversation_id: str) -> dict[str, Any]:
    with CONV_LOCK:
        conn = sqlite3.connect(CONV_DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT * FROM conversations WHERE id = ? AND agent_id = ?",
                (conversation_id, agent_id),
            ).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail=f"Conversation not found: {conversation_id}")
            return conv_row_to_dict(row)
        finally:
            conn.close()


def list_conversations(
    agent_id: str,
    query: str,
    archived: bool,
    limit: int,
    offset: int,
) -> tuple[list[dict[str, Any]], int]:
    safe_limit = max(1, min(limit, 200))
    safe_offset = max(0, offset)
    q = query.strip()

    where = "agent_id = ? AND archived = ?"
    params: list[Any] = [agent_id, 1 if archived else 0]
    if q:
        where += " AND title LIKE ?"
        params.append(f"%{q}%")

    with CONV_LOCK:
        conn = sqlite3.connect(CONV_DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            total = conn.execute(f"SELECT COUNT(*) AS cnt FROM conversations WHERE {where}", params).fetchone()["cnt"]
            rows = conn.execute(
                f"""
                SELECT *
                FROM conversations
                WHERE {where}
                ORDER BY pinned DESC, last_active_at DESC
                LIMIT ? OFFSET ?
                """,
                [*params, safe_limit, safe_offset],
            ).fetchall()
            return ([conv_row_to_dict(row) for row in rows], int(total))
        finally:
            conn.close()


def update_conversation_title(agent_id: str, conversation_id: str, title: str) -> dict[str, Any]:
    resolved_title = title.strip()
    if not resolved_title:
        raise HTTPException(status_code=400, detail="title must not be empty")

    now = now_iso()
    with CONV_LOCK:
        conn = sqlite3.connect(CONV_DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            result = conn.execute(
                """
                UPDATE conversations
                SET title = ?, updated_at = ?
                WHERE id = ? AND agent_id = ?
                """,
                (resolved_title, now, conversation_id, agent_id),
            )
            conn.commit()
            if result.rowcount == 0:
                raise HTTPException(status_code=404, detail=f"Conversation not found: {conversation_id}")
            row = conn.execute("SELECT * FROM conversations WHERE id = ?", (conversation_id,)).fetchone()
            return conv_row_to_dict(row)
        finally:
            conn.close()


def update_conversation_flag(agent_id: str, conversation_id: str, field: str, value: bool) -> dict[str, Any]:
    if field not in {"pinned", "archived"}:
        raise HTTPException(status_code=400, detail=f"invalid conversation field: {field}")

    now = now_iso()
    with CONV_LOCK:
        conn = sqlite3.connect(CONV_DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            result = conn.execute(
                f"UPDATE conversations SET {field} = ?, updated_at = ? WHERE id = ? AND agent_id = ?",
                (1 if value else 0, now, conversation_id, agent_id),
            )
            conn.commit()
            if result.rowcount == 0:
                raise HTTPException(status_code=404, detail=f"Conversation not found: {conversation_id}")
            row = conn.execute("SELECT * FROM conversations WHERE id = ?", (conversation_id,)).fetchone()
            return conv_row_to_dict(row)
        finally:
            conn.close()


def delete_conversation(agent_id: str, conversation_id: str) -> None:
    with CONV_LOCK:
        conn = sqlite3.connect(CONV_DB_PATH)
        try:
            conn.execute("DELETE FROM messages WHERE session_id = ?", (conversation_id,))
            result = conn.execute(
                "DELETE FROM conversations WHERE id = ? AND agent_id = ?",
                (conversation_id, agent_id),
            )
            conn.commit()
            if result.rowcount == 0:
                raise HTTPException(status_code=404, detail=f"Conversation not found: {conversation_id}")
        finally:
            conn.close()



def delete_conversations_by_agent(agent_id: str) -> dict[str, int]:
    with CONV_LOCK:
        conn = sqlite3.connect(CONV_DB_PATH)
        try:
            conv_rows = conn.execute(
                "SELECT id FROM conversations WHERE agent_id = ?",
                (agent_id,),
            ).fetchall()
            conversation_ids = [str(row[0]) for row in conv_rows]
            deleted_messages = 0
            for conversation_id in conversation_ids:
                result = conn.execute("DELETE FROM messages WHERE session_id = ?", (conversation_id,))
                deleted_messages += int(result.rowcount or 0)

            deleted_conversations = conn.execute(
                "DELETE FROM conversations WHERE agent_id = ?",
                (agent_id,),
            ).rowcount
            conn.commit()
            return {
                "conversations": int(deleted_conversations or 0),
                "messages": deleted_messages,
            }
        finally:
            conn.close()

def clear_conversation(agent_id: str, conversation_id: str) -> dict[str, Any]:
    now = now_iso()
    new_thread_id = f"thread-{uuid.uuid4().hex[:12]}"

    with CONV_LOCK:
        conn = sqlite3.connect(CONV_DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("DELETE FROM messages WHERE session_id = ?", (conversation_id,))
            result = conn.execute(
                """
                UPDATE conversations
                SET thread_id = ?,
                    message_count = 0,
                    last_message_preview = '',
                    updated_at = ?,
                    last_active_at = ?
                WHERE id = ? AND agent_id = ?
                """,
                (new_thread_id, now, now, conversation_id, agent_id),
            )
            conn.commit()
            if result.rowcount == 0:
                raise HTTPException(status_code=404, detail=f"Conversation not found: {conversation_id}")
            row = conn.execute("SELECT * FROM conversations WHERE id = ?", (conversation_id,)).fetchone()
            return conv_row_to_dict(row)
        finally:
            conn.close()


def message_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    try:
        tool_calls = json.loads(row["tool_calls"] or "[]")
    except Exception:
        tool_calls = []
    try:
        metadata = json.loads(row["metadata"] or "{}")
    except Exception:
        metadata = {}
    return {
        "id": row["id"],
        "session_id": row["session_id"],
        "role": row["role"],
        "content": row["content"],
        "tool_calls": tool_calls if isinstance(tool_calls, list) else [],
        "metadata": metadata if isinstance(metadata, dict) else {},
        "created_at": row["created_at"],
    }


def list_messages(session_id: str, limit: int = 200, offset: int = 0) -> tuple[list[dict[str, Any]], int]:
    safe_limit = max(1, min(limit, 500))
    safe_offset = max(0, offset)

    with CONV_LOCK:
        conn = sqlite3.connect(CONV_DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            total = conn.execute(
                "SELECT COUNT(*) AS cnt FROM messages WHERE session_id = ?",
                (session_id,),
            ).fetchone()["cnt"]
            rows = conn.execute(
                """
                SELECT *
                FROM messages
                WHERE session_id = ?
                ORDER BY created_at ASC
                LIMIT ? OFFSET ?
                """,
                (session_id, safe_limit, safe_offset),
            ).fetchall()
            return ([message_row_to_dict(row) for row in rows], int(total))
        finally:
            conn.close()


def insert_message(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    role: str,
    content: str,
    tool_calls: list[dict[str, Any]] | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO messages (id, session_id, role, content, tool_calls, metadata, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            uuid.uuid4().hex,
            session_id,
            role,
            content,
            json.dumps(tool_calls or [], ensure_ascii=False),
            json.dumps(metadata or {}, ensure_ascii=False),
            now_iso(),
        ),
    )


def conversation_record_turn(conversation_id: str, user_message: str, assistant_message: str) -> None:
    preview_raw = assistant_message.strip() or user_message.strip()
    preview = preview_raw.replace("\n", " ").strip()
    if len(preview) > 280:
        preview = preview[:277] + "..."

    increment = 2 if assistant_message.strip() else 1
    now = now_iso()

    with CONV_LOCK:
        conn = sqlite3.connect(CONV_DB_PATH)
        try:
            if user_message.strip():
                insert_message(conn, session_id=conversation_id, role="user", content=user_message)
            if assistant_message.strip():
                insert_message(conn, session_id=conversation_id, role="assistant", content=assistant_message)
            conn.execute(
                """
                UPDATE conversations
                SET message_count = message_count + ?,
                    last_message_preview = ?,
                    updated_at = ?,
                    last_active_at = ?
                WHERE id = ?
                """,
                (increment, preview, now, now, conversation_id),
            )
            conn.commit()
        finally:
            conn.close()


def list_sessions_v1(
    query: str,
    limit: int,
    offset: int,
    agent_id: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    safe_limit = max(1, min(limit, 200))
    safe_offset = max(0, offset)
    q = query.strip()

    where_parts: list[str] = ["archived = 0"]
    params: list[Any] = []
    if agent_id:
        where_parts.append("agent_id = ?")
        params.append(agent_id)
    if q:
        where_parts.append("title LIKE ?")
        params.append(f"%{q}%")
    where = " AND ".join(where_parts)

    with CONV_LOCK:
        conn = sqlite3.connect(CONV_DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            total = conn.execute(f"SELECT COUNT(*) AS cnt FROM conversations WHERE {where}", params).fetchone()["cnt"]
            rows = conn.execute(
                f"""
                SELECT *
                FROM conversations
                WHERE {where}
                ORDER BY pinned DESC, last_active_at DESC
                LIMIT ? OFFSET ?
                """,
                [*params, safe_limit, safe_offset],
            ).fetchall()
            return ([conv_row_to_dict(row) for row in rows], int(total))
        finally:
            conn.close()



def template_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    try:
        model_config = json.loads(row["model_config"] or "{}")
    except Exception:
        model_config = {}
    try:
        tools_config = json.loads(row["tools_config"] or "{}")
    except Exception:
        tools_config = {}
    return {
        "id": row["id"],
        "name": row["name"],
        "system_prompt": row["system_prompt"],
        "model_config": model_config if isinstance(model_config, dict) else {},
        "tools_config": tools_config if isinstance(tools_config, dict) else {},
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def list_templates(limit: int = 100, offset: int = 0) -> tuple[list[dict[str, Any]], int]:
    safe_limit = max(1, min(limit, 200))
    safe_offset = max(0, offset)
    with CONV_LOCK:
        conn = sqlite3.connect(CONV_DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            total = conn.execute("SELECT COUNT(*) AS cnt FROM agent_templates").fetchone()["cnt"]
            rows = conn.execute(
                """
                SELECT *
                FROM agent_templates
                ORDER BY updated_at DESC
                LIMIT ? OFFSET ?
                """,
                (safe_limit, safe_offset),
            ).fetchall()
            return ([template_row_to_dict(row) for row in rows], int(total))
        finally:
            conn.close()


def get_template_or_404(template_id: str) -> dict[str, Any]:
    with CONV_LOCK:
        conn = sqlite3.connect(CONV_DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT * FROM agent_templates WHERE id = ?",
                (template_id,),
            ).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail=f"Template not found: {template_id}")
            return template_row_to_dict(row)
        finally:
            conn.close()




