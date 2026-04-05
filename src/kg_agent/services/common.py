from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _resolve_env_path(path: str) -> Path | None:
    candidate = Path(path).expanduser()
    if candidate.is_absolute():
        return candidate if candidate.exists() else None

    cwd_candidate = (Path.cwd() / candidate).resolve()
    if cwd_candidate.exists():
        return cwd_candidate

    repo_candidate = (REPO_ROOT / candidate).resolve()
    if repo_candidate.exists():
        return repo_candidate

    return None


def load_dotenv(path: str) -> None:
    if not path:
        return

    dotenv_path = _resolve_env_path(path)
    if dotenv_path is None:
        return

    with dotenv_path.open("r", encoding="utf-8") as fp:
        for raw_line in fp:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue

            key, value = line.split("=", 1)
            env_key = key.strip()
            env_value = value.strip()
            if not env_key:
                continue

            if env_value.startswith(("\"", "'")) and env_value.endswith(("\"", "'")) and len(env_value) >= 2:
                env_value = env_value[1:-1]

            os.environ.setdefault(env_key, env_value)
