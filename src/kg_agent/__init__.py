from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .config import AgentConfig, MCPServerConfig, load_config

if TYPE_CHECKING:
    from .graph import AgentRuntime

__all__ = [
    "AgentConfig",
    "MCPServerConfig",
    "AgentRuntime",
    "build_agent",
    "build_agent_async",
    "load_config",
]


def build_agent(*args: Any, **kwargs: Any) -> Any:
    from .graph import build_agent as _build_agent

    return _build_agent(*args, **kwargs)


def build_agent_async(*args: Any, **kwargs: Any) -> Any:
    from .graph import build_agent_async as _build_agent_async

    return _build_agent_async(*args, **kwargs)
