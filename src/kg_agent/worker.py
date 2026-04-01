from __future__ import annotations

import argparse
import asyncio
from typing import Any

from .services import run_memory_job
from .services.queue import redis_settings_from_env


async def summarize_session_memory_job(ctx: dict[str, Any], job_id: str) -> dict[str, Any]:
    await asyncio.to_thread(run_memory_job, job_id)
    return {"ok": True, "job_id": job_id}


class WorkerSettings:
    functions = [summarize_session_memory_job]
    redis_settings = redis_settings_from_env()
    max_jobs = 10


def main() -> None:
    parser = argparse.ArgumentParser(description="Run ARQ worker for KG Agent background jobs")
    parser.add_argument("--check-only", action="store_true", help="Only validate worker settings and exit")
    args = parser.parse_args()

    if args.check_only:
        print("worker settings ok")
        return

    try:
        from arq.cli import run_worker
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(f"arq is not installed: {exc}") from exc

    run_worker(WorkerSettings)


if __name__ == "__main__":
    main()
