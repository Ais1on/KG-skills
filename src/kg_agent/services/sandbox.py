from __future__ import annotations

import time
from typing import Any

from fastapi import HTTPException


def _run_docker_python(code: str, timeout_sec: int) -> dict[str, Any]:
    try:
        import docker  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail=f"docker sdk is not installed: {exc}") from exc

    started = time.perf_counter()

    try:
        client = docker.from_env()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Docker daemon unavailable: {exc}") from exc

    container = None
    try:
        container = client.containers.run(
            "python:3.10-slim",
            command=["python", "-c", code],
            mem_limit="256m",
            network_disabled=True,
            detach=True,
            stdout=True,
            stderr=True,
            remove=False,
        )
        result = container.wait(timeout=timeout_sec)
        status_code = int(result.get("StatusCode", -1)) if isinstance(result, dict) else -1
        logs = container.logs(stdout=True, stderr=True).decode("utf-8", errors="replace")
        elapsed = int((time.perf_counter() - started) * 1000)

        if status_code == 0:
            return {
                "stdout": logs,
                "stderr": "",
                "exit_code": status_code,
                "execution_time_ms": elapsed,
                "runtime": "docker",
            }

        return {
            "stdout": "",
            "stderr": logs,
            "exit_code": status_code,
            "execution_time_ms": elapsed,
            "runtime": "docker",
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Sandbox execution failed: {exc}") from exc
    finally:
        if container is not None:
            try:
                container.remove(force=True)
            except Exception:
                pass


def execute_sandbox_code(language: str, code: str, timeout_sec: int = 10) -> dict[str, Any]:
    if language.strip().lower() not in {"python", "python3"}:
        raise HTTPException(status_code=400, detail=f"Unsupported language: {language}")

    text = code.strip()
    if not text:
        raise HTTPException(status_code=400, detail="code must not be empty")

    safe_timeout = max(1, min(int(timeout_sec), 120))
    return _run_docker_python(text, safe_timeout)
