from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_dotenv(path: str) -> None:
    if not path:
        return

    dotenv_path = Path(path)
    if not dotenv_path.exists():
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

            if env_value.startswith((""", "'")) and env_value.endswith((""", "'")) and len(env_value) >= 2:
                env_value = env_value[1:-1]

            os.environ.setdefault(env_key, env_value)
