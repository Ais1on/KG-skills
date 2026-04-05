from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class MCPServerConfig:
    transport: str = "stdio"
    command: str = ""
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class AgentConfig:
    model: str = "deepseek-chat"
    api_base: str = "https://api.deepseek.com/v1"
    api_key_env: str = "DEEPSEEK_API_KEY"
    temperature: float = 0.0
    skills_dir: str = "skills"
    local_tool_modules: list[str] = field(default_factory=lambda: ["kg_agent.builtin_tools"])
    mcp_servers: dict[str, MCPServerConfig] = field(default_factory=dict)
    memory_backend: str = "sqlite"
    memory_path: str = ".kg_agent/checkpoints.sqlite"
    redis_url: str = ""
    redis_key_prefix: str = "kg:langgraph:checkpoint"
    redis_ttl_seconds: int = 0
    system_prompt: str = ""
    dangerous_tools: list[str] = field(default_factory=list)
