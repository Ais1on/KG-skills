from __future__ import annotations

import os
from typing import Any

from fastapi import HTTPException


def _redis_settings() -> Any:
    try:
        from arq.connections import RedisSettings
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail=f"arq is not installed: {exc}") from exc

    host = os.environ.get("KG_REDIS_HOST", "127.0.0.1")
    port = int(os.environ.get("KG_REDIS_PORT", "6379"))
    database = int(os.environ.get("KG_REDIS_DB", "0"))
    password = os.environ.get("KG_REDIS_PASSWORD") or None
    return RedisSettings(host=host, port=port, database=database, password=password)


async def enqueue_memory_job_arq(job_id: str) -> str:
    try:
        from arq import create_pool
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail=f"arq is not installed: {exc}") from exc

    settings = _redis_settings()

    try:
        redis = await create_pool(settings)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Redis unavailable: {exc}") from exc

    try:
        job = await redis.enqueue_job(
            "summarize_session_memory_job",
            job_id,
            _job_id=f"memory:{job_id}",
        )
        if job is None:
            raise HTTPException(status_code=503, detail="Failed to enqueue memory job")
        return str(job.job_id)
    finally:
        await redis.close()


def redis_settings_from_env() -> Any:
    return _redis_settings()
