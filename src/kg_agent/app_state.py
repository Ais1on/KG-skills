from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from threading import Lock

from .config import AgentConfig
from .graph import AgentRuntime


@dataclass(slots=True)
class ManagedAgent:
    agent_id: str
    name: str
    created_at: str
    config: AgentConfig
    runtime: AgentRuntime


APP_ROOT = Path(__file__).resolve().parent
WORKSPACE_ROOT = Path.cwd().resolve()
FRONTEND_DIST = WORKSPACE_ROOT / "frontend" / "dist"
FRONTEND_ASSETS = FRONTEND_DIST / "assets"
LEGACY_INDEX_HTML = APP_ROOT / "web" / "index.html"
CONV_DB_PATH = WORKSPACE_ROOT / ".kg_agent" / "conversations.sqlite"

AGENT_STORE: dict[str, ManagedAgent] = {}
AGENT_LOCK = Lock()
CONV_LOCK = Lock()


TOOL_CONFIRMATIONS: dict[str, dict[str, object]] = {}
TOOL_CONFIRM_LOCK = Lock()
