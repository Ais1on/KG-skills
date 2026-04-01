from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import BaseTool, tool
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from .config import AgentConfig
from .loaders.mcp_loader import MCPLoadResult, load_mcp_tools
from .loaders.skill_loader import SkillDefinition, discover_skills, format_skill_catalog, invoke_skill
from .loaders.tool_loader import load_local_tools


class AgentState(TypedDict):
    messages: Annotated[list[Any], add_messages]


@dataclass(slots=True)
class AgentRuntime:
    graph: Any
    skills: dict[str, SkillDefinition]
    warnings: list[str]
    tools: list[BaseTool]
    _mcp_clients: list[Any]
    _checkpointer: Any
    dangerous_tools: set[str]

    def ask(self, message: str, thread_id: str = "default") -> str:
        result = self.graph.invoke(
            {"messages": [HumanMessage(content=message)]},
            config={"configurable": {"thread_id": thread_id}},
        )
        last_message = result["messages"][-1]
        content = getattr(last_message, "content", "")
        if isinstance(content, str):
            return content
        return json.dumps(content, ensure_ascii=False)


def _run_skill_by_llm(llm: ChatOpenAI, skill: SkillDefinition, payload: dict[str, Any]) -> Any:
    response = llm.invoke(
        [
            SystemMessage(
                content=(
                    "You are executing a skill spec."
                    " Follow the spec strictly and produce JSON when possible.\n\n"
                    f"Skill name: {skill.name}\n"
                    f"Description: {skill.description}\n"
                    f"Spec:\n{skill.body}"
                )
            ),
            HumanMessage(content=json.dumps(payload, ensure_ascii=False)),
        ]
    )
    return getattr(response, "content", "")


def _build_skill_tools(skills: dict[str, SkillDefinition], llm: ChatOpenAI) -> list[BaseTool]:
    @tool
    def list_skills() -> str:
        """List all loaded skills and their short descriptions."""
        records = [
            {
                "name": item.name,
                "display_name": item.display_name,
                "description": item.description,
                "short_description": item.short_description,
            }
            for item in skills.values()
        ]
        return json.dumps(records, ensure_ascii=False)

    @tool
    def read_skill(skill_name: str) -> str:
        """Read a specific skill specification by skill_name."""
        skill = skills.get(skill_name)
        if skill is None:
            return json.dumps({"ok": False, "error": f"Skill not found: {skill_name}"}, ensure_ascii=False)
        return json.dumps(
            {
                "ok": True,
                "name": skill.name,
                "display_name": skill.display_name,
                "description": skill.description,
                "default_prompt": skill.default_prompt,
                "spec": skill.body,
            },
            ensure_ascii=False,
        )

    @tool
    def invoke_skill_tool(skill_name: str, payload_json: str = "{}") -> str:
        """Invoke a skill by name with a JSON payload string."""
        try:
            payload = json.loads(payload_json)
        except json.JSONDecodeError as exc:
            return json.dumps({"ok": False, "error": f"Invalid payload_json: {exc}"}, ensure_ascii=False)

        if not isinstance(payload, dict):
            return json.dumps({"ok": False, "error": "payload_json must decode to an object"}, ensure_ascii=False)

        skill = skills.get(skill_name)
        if skill is None:
            return json.dumps({"ok": False, "error": f"Skill not found: {skill_name}"}, ensure_ascii=False)

        result = invoke_skill(skills, skill_name, payload)
        if result.ok and isinstance(result.output, dict) and result.output.get("mode") == "spec_only":
            llm_output = _run_skill_by_llm(llm, skill, payload)
            return json.dumps(
                {
                    "ok": True,
                    "skill": skill_name,
                    "mode": "llm_from_spec",
                    "output": llm_output,
                },
                ensure_ascii=False,
            )

        return json.dumps(
            {
                "ok": result.ok,
                "skill": result.skill,
                "output": result.output,
                "error": result.error,
            },
            ensure_ascii=False,
        )

    return [list_skills, read_skill, invoke_skill_tool]


def _build_system_prompt(skills: dict[str, SkillDefinition], warnings: list[str], custom_prompt: str = "") -> str:
    skill_catalog = format_skill_catalog(skills)
    warning_text = "\n".join(f"- {item}" for item in warnings) if warnings else "- None"

    prefix = custom_prompt.strip()
    if prefix:
        return prefix + "\n\n" + (
            "Loaded skills:\n"
            f"{skill_catalog}\n"
            "\n"
            "Runtime warnings:\n"
            f"{warning_text}"
        )

    return (
        "You are a LangGraph threat-intel assistant.\n"
        "Use tools when needed, and prioritize structured JSON outputs for technical tasks.\n"
        "\n"
        "Loaded skills:\n"
        f"{skill_catalog}\n"
        "\n"
        "Runtime warnings:\n"
        f"{warning_text}\n"
        "\n"
        "When user requests a specific skill, call read_skill first if needed, then call invoke_skill_tool."
    )




def _message_tool_call_names(message: Any) -> list[str]:
    calls = getattr(message, "tool_calls", None)
    if not isinstance(calls, list):
        return []

    names: list[str] = []
    for item in calls:
        if isinstance(item, dict):
            name = str(item.get("name", "")).strip()
        else:
            name = str(getattr(item, "name", "")).strip()
        if name:
            names.append(name)
    return names

def _collect_tools(
    config: AgentConfig,
    skills: dict[str, SkillDefinition],
    llm: ChatOpenAI,
) -> tuple[list[BaseTool], MCPLoadResult]:
    local_tools = load_local_tools(config.local_tool_modules)
    skill_tools = _build_skill_tools(skills, llm)
    mcp_result = load_mcp_tools(config.mcp_servers)
    all_tools = [*local_tools, *skill_tools, *mcp_result.tools]
    return all_tools, mcp_result


def _build_model(config: AgentConfig) -> ChatOpenAI:
    api_key = os.environ.get(config.api_key_env, "").strip()
    if not api_key:
        raise ValueError(f"Missing API key in environment variable: {config.api_key_env}")

    return ChatOpenAI(
        model=config.model,
        temperature=config.temperature,
        base_url=config.api_base,
        api_key=api_key,
    )


def _build_checkpointer(config: AgentConfig, warnings: list[str]) -> Any:
    backend = (config.memory_backend or "memory").strip().lower()

    if backend in {"memory", "inmemory", "ram"}:
        return MemorySaver()

    if backend in {"sqlite", "sqlite3"}:
        try:
            from langgraph.checkpoint.sqlite import SqliteSaver
        except Exception as exc:  # pragma: no cover
            warnings.append(
                "SQLite checkpointer is unavailable. Install langgraph-checkpoint-sqlite and retry. "
                f"Fallback to MemorySaver. detail={exc}"
            )
            return MemorySaver()

        raw_path = (config.memory_path or "").strip() or ".kg_agent/checkpoints.sqlite"
        try:
            if raw_path != ":memory:":
                path_obj = Path(raw_path)
                path_obj.parent.mkdir(parents=True, exist_ok=True)
                conn_str = str(path_obj)
            else:
                conn_str = raw_path

            return SqliteSaver.from_conn_string(conn_str)
        except Exception as exc:  # pragma: no cover
            warnings.append(f"Failed to init sqlite checkpointer ({raw_path}), fallback to memory: {exc}")
            return MemorySaver()

    warnings.append(f"Unknown memory_backend '{config.memory_backend}', fallback to memory")
    return MemorySaver()


def build_agent(config: AgentConfig) -> AgentRuntime:
    skills = discover_skills(Path(config.skills_dir))

    llm = _build_model(config)
    all_tools, mcp_result = _collect_tools(config, skills, llm)

    llm_with_tools = llm.bind_tools(all_tools)
    system_prompt = _build_system_prompt(skills, mcp_result.warnings, config.system_prompt)

    def assistant_node(state: AgentState) -> dict[str, list[Any]]:
        response = llm_with_tools.invoke([SystemMessage(content=system_prompt), *state["messages"]])
        return {"messages": [response]}

    graph_builder = StateGraph(AgentState)
    graph_builder.add_node("assistant", assistant_node)
    graph_builder.add_node("tools", ToolNode(tools=all_tools))
    graph_builder.add_node("danger_tools_node", ToolNode(tools=all_tools))

    configured_dangerous = {item.strip() for item in (config.dangerous_tools or []) if item.strip()}
    dangerous_lower = {item.lower() for item in configured_dangerous}

    def route_after_assistant(state: AgentState) -> str:
        messages = state.get("messages") or []
        if not messages:
            return "end"
        last = messages[-1]
        tool_call_names = _message_tool_call_names(last)
        if not tool_call_names:
            return "end"
        if any(name.lower() in dangerous_lower for name in tool_call_names):
            return "danger"
        return "safe"

    graph_builder.add_edge(START, "assistant")
    graph_builder.add_conditional_edges(
        "assistant",
        route_after_assistant,
        {
            "safe": "tools",
            "danger": "danger_tools_node",
            "end": END,
        },
    )
    graph_builder.add_edge("tools", "assistant")
    graph_builder.add_edge("danger_tools_node", "assistant")

    checkpointer = _build_checkpointer(config, mcp_result.warnings)
    interrupt_before = ["danger_tools_node"] if dangerous_lower else None
    graph = graph_builder.compile(checkpointer=checkpointer, interrupt_before=interrupt_before)
    return AgentRuntime(
        graph=graph,
        skills=skills,
        warnings=mcp_result.warnings,
        tools=all_tools,
        _mcp_clients=mcp_result.clients,
        _checkpointer=checkpointer,
        dangerous_tools=configured_dangerous,
    )
