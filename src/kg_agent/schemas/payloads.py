from __future__ import annotations

from pydantic import BaseModel, Field


class MCPServerPayload(BaseModel):
    name: str
    transport: str = "stdio"
    command: str = ""
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)


class AgentCreatePayload(BaseModel):
    name: str | None = None
    model: str = "deepseek-chat"
    api_base: str = "https://api.deepseek.com/v1"
    api_key_env: str = "DEEPSEEK_API_KEY"
    temperature: float = 0.0
    skills_dir: str = "skills"
    local_tool_modules: list[str] = Field(default_factory=lambda: ["kg_agent.builtin_tools"])
    mcp_servers: list[MCPServerPayload] = Field(default_factory=list)
    memory_backend: str = "sqlite"
    memory_path: str = ".kg_agent/checkpoints.sqlite"
    system_prompt: str = ""
    dangerous_tools: list[str] = Field(default_factory=list)
    env_file: str = ".env"


class AgentPatchPayload(BaseModel):
    name: str


class ConversationCreatePayload(BaseModel):
    title: str | None = None
    thread_id: str | None = None


class ConversationPatchPayload(BaseModel):
    title: str


class ConversationPinPayload(BaseModel):
    pinned: bool


class ConversationArchivePayload(BaseModel):
    archived: bool


class SessionCreatePayload(BaseModel):
    title: str | None = None
    thread_id: str | None = None
    agent_id: str = "default"


class ChatPayload(BaseModel):
    message: str
    thread_id: str = "default"
    conversation_id: str | None = None


class SaveConfigPayload(BaseModel):
    path: str


class AgentFromTemplatePayload(BaseModel):
    template_id: str
    agent_name: str | None = None
    session_title: str | None = None
    env_file: str = ".env"


class ToolConfirmPayload(BaseModel):
    confirmation_id: str
    approved: bool


class MemorySummarizePayload(BaseModel):
    max_messages: int = 20


class SandboxExecutePayload(BaseModel):
    session_id: str
    language: str = "python"
    code: str
    timeout_sec: int = 10
