from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from ..schemas import SandboxExecutePayload
from ..services import execute_sandbox_code

router = APIRouter()


@router.post("/api/v1/sandbox/execute")
def execute_sandbox(payload: SandboxExecutePayload) -> dict[str, Any]:
    result = execute_sandbox_code(payload.language, payload.code, timeout_sec=payload.timeout_sec)
    return {
        "session_id": payload.session_id,
        "language": payload.language,
        **result,
    }
