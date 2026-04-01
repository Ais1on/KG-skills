from __future__ import annotations

from typing import Any

from fastapi import APIRouter, status

from ..schemas import MemorySummarizePayload
from ..services import (
    create_memory_job,
    enqueue_memory_job_arq,
    get_memory_job,
    list_session_memories,
    mark_memory_job_error,
)

router = APIRouter()


@router.post("/api/v1/sessions/{session_id}/memory/summarize", status_code=status.HTTP_202_ACCEPTED)
async def summarize_session_memory(
    session_id: str,
    payload: MemorySummarizePayload,
) -> dict[str, Any]:
    job = create_memory_job(session_id, payload.max_messages)
    job_id = str(job["job_id"])

    try:
        queue_job_id = await enqueue_memory_job_arq(job_id)
    except Exception as exc:
        mark_memory_job_error(job_id, str(exc))
        raise

    return {
        "ok": True,
        "status": "queued",
        "job_id": job_id,
        "queue_job_id": queue_job_id,
        "session_id": session_id,
        "queue": "arq",
    }


@router.get("/api/v1/memory/jobs/{job_id}")
def get_memory_summarize_job(job_id: str) -> dict[str, Any]:
    return get_memory_job(job_id)


@router.get("/api/v1/sessions/{session_id}/memories")
def list_session_memory(
    session_id: str,
    limit: int = 20,
    offset: int = 0,
) -> dict[str, Any]:
    items, total = list_session_memories(session_id, limit=limit, offset=offset)
    return {
        "items": items,
        "total": total,
        "limit": max(1, min(limit, 200)),
        "offset": max(0, offset),
    }
