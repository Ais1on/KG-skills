from __future__ import annotations

import asyncio
import json
import operator
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, TypedDict

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool, tool
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from .checkpoints import build_redis_checkpointer
from .config import AgentConfig
from .kg_workflow import (
    TextExtractionResult,
    coerce_extraction_result,
    detect_workflow_mode,
    extract_python_code,
    normalize_graph_payload,
    summarize_graph_payload,
)
from .loaders.mcp_loader import MCPLoadResult, load_mcp_tools
from .loaders.skill_loader import SkillDefinition, discover_skills, format_skill_catalog, invoke_skill
from .loaders.tool_loader import load_local_tools


class AgentState(TypedDict, total=False):
    messages: Annotated[list[Any], add_messages]
    raw_input: str
    entities: Annotated[list[dict[str, Any]], operator.add]
    triplets: Annotated[list[dict[str, Any]], operator.add]
    current_skill: str
    sandbox_code: str
    sandbox_result: str
    error_log: str


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

    async def aask(self, message: str, thread_id: str = "default") -> str:
        result = await self.graph.ainvoke(
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


def _latest_human_message(messages: list[Any]) -> HumanMessage | None:
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            return message
    return None


def _extract_message_text(message: Any) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text") or item.get("content")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts)
    return str(content or "")


def _has_tavily_tool(tools: list[BaseTool]) -> bool:
    for tool_item in tools:
        if str(getattr(tool_item, "name", "")).strip() == "tavily_search":
            return True
    return False


def _requires_tavily_search(message_text: str) -> bool:
    text = message_text.lower()
    keywords = [
        "latest",
        "recent",
        "today",
        "news",
        "search",
        "最新",
        "最近",
        "今天",
        "新闻",
        "搜索",
        "漏洞",
        "cve",
    ]
    return any(keyword in text for keyword in keywords)


def _has_recent_tavily_result(messages: list[Any]) -> bool:
    for message in reversed(messages):
        if isinstance(message, ToolMessage) and str(getattr(message, "name", "")).strip() == "tavily_search":
            return True
    return False


def _forced_tavily_tool_call(message_text: str) -> AIMessage:
    topic = "news" if any(key in message_text.lower() for key in ["latest", "news", "最新", "新闻", "漏洞", "cve"]) else "general"
    return AIMessage(
        content="",
        tool_calls=[
            {
                "name": "tavily_search",
                "args": {
                    "query": message_text,
                    "max_results": 5,
                    "topic": topic,
                    "include_answer": True,
                },
                "id": "forced-tavily-search",
                "type": "tool_call",
            }
        ],
    )


def _recent_tool_context(messages: list[Any], limit: int = 4) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    for message in reversed(messages):
        if not isinstance(message, ToolMessage):
            continue
        records.append(
            {
                "tool": str(getattr(message, "name", "")).strip() or "tool",
                "content": _extract_message_text(message)[:4000],
            }
        )
        if len(records) >= limit:
            break
    records.reverse()
    return records


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


async def _build_checkpointer_async(config: AgentConfig, warnings: list[str]) -> Any:
    backend = (config.memory_backend or "memory").strip().lower()

    if backend in {"memory", "inmemory", "ram"}:
        return MemorySaver()

    if backend == "redis":
        return build_redis_checkpointer(config)

    if backend in {"sqlite", "sqlite3"}:
        try:
            from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
        except Exception as exc:  # pragma: no cover
            warnings.append(
                "Async SQLite checkpointer is unavailable. Install langgraph-checkpoint-sqlite and aiosqlite, then retry. "
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

            saver_cm = AsyncSqliteSaver.from_conn_string(conn_str)
            saver = await saver_cm.__aenter__()
            conn = getattr(saver, "conn", None)
            if conn is not None and not hasattr(conn, "is_alive") and hasattr(conn, "_running"):
                setattr(conn, "is_alive", lambda: bool(getattr(conn, "_running", False)))
            setattr(saver, "_kg_agent_context_manager", saver_cm)
            await saver.setup()
            return saver
        except Exception as exc:  # pragma: no cover
            warnings.append(f"Failed to init async sqlite checkpointer ({raw_path}), fallback to memory: {exc}")
            return MemorySaver()

    warnings.append(f"Unknown memory_backend '{config.memory_backend}', fallback to memory")
    return MemorySaver()


def _build_checkpointer(config: AgentConfig, warnings: list[str]) -> Any:
    return asyncio.run(_build_checkpointer_async(config, warnings))


async def build_agent_async(config: AgentConfig) -> AgentRuntime:
    skills = discover_skills(Path(config.skills_dir))

    llm = _build_model(config)
    all_tools, mcp_result = _collect_tools(config, skills, llm)

    llm_with_tools = llm.bind_tools(all_tools)
    extraction_llm = llm.with_structured_output(TextExtractionResult)
    system_prompt = _build_system_prompt(skills, mcp_result.warnings, config.system_prompt)

    def orchestrator_node(state: AgentState) -> dict[str, Any]:
        messages = state.get("messages") or []
        latest_human = _latest_human_message(messages)
        raw_input = _extract_message_text(latest_human).strip() if latest_human is not None else str(state.get("raw_input") or "").strip()
        current_skill = detect_workflow_mode(raw_input) if raw_input else str(state.get("current_skill") or "assistant")
        return {
            "raw_input": raw_input,
            "current_skill": current_skill or "assistant",
            "error_log": "",
        }

    def search_gate_node(state: AgentState) -> dict[str, list[Any]]:
        messages = state.get("messages") or []
        if not _has_tavily_tool(all_tools):
            return {"messages": []}
        if _has_recent_tavily_result(messages):
            return {"messages": []}
        latest_human = _latest_human_message(messages)
        if latest_human is None:
            return {"messages": []}
        message_text = _extract_message_text(latest_human).strip()
        if not message_text or not _requires_tavily_search(message_text):
            return {"messages": []}
        return {"messages": [_forced_tavily_tool_call(message_text)]}

    async def text_extraction_skill_node(state: AgentState) -> dict[str, Any]:
        raw_input = str(state.get("raw_input") or "").strip()
        tool_context = _recent_tool_context(state.get("messages") or [])
        response = await extraction_llm.ainvoke(
            [
                SystemMessage(
                    content=(
                        "Extract knowledge graph candidates from the user input and optional tool results.\n"
                        "Return entities, triplets, and sandbox_code only.\n"
                        "Only set sandbox_code when Python execution is genuinely needed."
                    )
                ),
                HumanMessage(
                    content=json.dumps(
                        {
                            "raw_input": raw_input,
                            "tool_context": tool_context,
                        },
                        ensure_ascii=False,
                    )
                ),
            ]
        )
        payload = coerce_extraction_result(response.model_dump())
        return {
            "entities": payload.get("entities") if isinstance(payload.get("entities"), list) else [],
            "triplets": payload.get("triplets") if isinstance(payload.get("triplets"), list) else [],
            "sandbox_code": str(payload.get("sandbox_code") or "").strip(),
            "error_log": "",
        }

    async def assistant_node(state: AgentState) -> dict[str, list[Any]]:
        stream = llm_with_tools.astream([SystemMessage(content=system_prompt), *state["messages"]])
        aggregate = None
        async for chunk in stream:
            aggregate = chunk if aggregate is None else aggregate + chunk

        if aggregate is None:
            return {"messages": [AIMessage(content="")]}

        payload = aggregate.model_dump(exclude={"type", "tool_call_chunks", "chunk_position"})
        return {"messages": [AIMessage(**payload)]}

    async def sandbox_node(state: AgentState) -> dict[str, Any]:
        code = str(state.get("sandbox_code") or "").strip() or extract_python_code(str(state.get("raw_input") or ""))
        if not code:
            return {"sandbox_result": "", "error_log": "sandbox code is empty"}

        try:
            from .services.sandbox import execute_sandbox_code

            result = await asyncio.to_thread(execute_sandbox_code, "python", code, 10)
        except Exception as exc:
            return {"sandbox_result": "", "error_log": str(exc)}

        return {
            "sandbox_code": code,
            "sandbox_result": json.dumps(result, ensure_ascii=False),
            "error_log": "",
        }

    def validator_node(state: AgentState) -> dict[str, Any]:
        normalized = normalize_graph_payload(
            {
                "entities": state.get("entities") or [],
                "triplets": state.get("triplets") or [],
                "sandbox_result": state.get("sandbox_result") or "",
            }
        )
        return {
            "entities": normalized["entities"],
            "triplets": normalized["triplets"],
            "sandbox_result": normalized["sandbox_result"],
            "error_log": state.get("error_log") or "",
        }

    def finalizer_node(state: AgentState) -> dict[str, list[Any]]:
        summary = summarize_graph_payload(
            {
                "entities": state.get("entities") or [],
                "triplets": state.get("triplets") or [],
                "sandbox_result": state.get("sandbox_result") or "",
            }
        )
        return {"messages": [AIMessage(content=summary)]}

    graph_builder = StateGraph(AgentState)
    graph_builder.add_node("orchestrator", orchestrator_node)
    graph_builder.add_node("search_gate", search_gate_node)
    graph_builder.add_node("text_extraction_skill", text_extraction_skill_node)
    graph_builder.add_node("assistant", assistant_node)
    graph_builder.add_node("tools", ToolNode(tools=all_tools))
    graph_builder.add_node("danger_tools_node", ToolNode(tools=all_tools))
    graph_builder.add_node("sandbox", sandbox_node)
    graph_builder.add_node("validator", validator_node)
    graph_builder.add_node("finalizer", finalizer_node)

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

    def route_from_orchestrator(state: AgentState) -> str:
        raw_input = str(state.get("raw_input") or "").strip()
        current_skill = str(state.get("current_skill") or "assistant").strip() or "assistant"
        should_search = bool(raw_input) and _has_tavily_tool(all_tools) and _requires_tavily_search(raw_input) and not _has_recent_tavily_result(state.get("messages") or [])
        if should_search:
            return "search_gate"
        if current_skill == "text_extraction_skill":
            return "text_extraction_skill"
        if current_skill == "code_sandbox":
            return "sandbox"
        return "assistant"

    def route_after_search_gate(state: AgentState) -> str:
        messages = state.get("messages") or []
        if not messages:
            current_skill = str(state.get("current_skill") or "assistant").strip() or "assistant"
            if current_skill == "text_extraction_skill":
                return "text_extraction_skill"
            if current_skill == "code_sandbox":
                return "sandbox"
            return "assistant"
        last = messages[-1]
        tool_call_names = _message_tool_call_names(last)
        if tool_call_names:
            if any(name.lower() in dangerous_lower for name in tool_call_names):
                return "danger"
            return "safe"
        current_skill = str(state.get("current_skill") or "assistant").strip() or "assistant"
        if current_skill == "text_extraction_skill":
            return "text_extraction_skill"
        if current_skill == "code_sandbox":
            return "sandbox"
        return "assistant"

    def route_after_tools(state: AgentState) -> str:
        current_skill = str(state.get("current_skill") or "assistant").strip() or "assistant"
        if current_skill == "text_extraction_skill":
            return "text_extraction_skill"
        return "assistant"

    def route_after_text_extraction(state: AgentState) -> str:
        if str(state.get("sandbox_code") or "").strip():
            return "sandbox"
        return "validator"

    graph_builder.add_edge(START, "orchestrator")
    graph_builder.add_conditional_edges(
        "orchestrator",
        route_from_orchestrator,
        {
            "search_gate": "search_gate",
            "text_extraction_skill": "text_extraction_skill",
            "sandbox": "sandbox",
            "assistant": "assistant",
        },
    )
    graph_builder.add_conditional_edges(
        "search_gate",
        route_after_search_gate,
        {
            "assistant": "assistant",
            "text_extraction_skill": "text_extraction_skill",
            "sandbox": "sandbox",
            "safe": "tools",
            "danger": "danger_tools_node",
        },
    )
    graph_builder.add_conditional_edges(
        "assistant",
        route_after_assistant,
        {
            "safe": "tools",
            "danger": "danger_tools_node",
            "end": END,
        },
    )
    graph_builder.add_conditional_edges(
        "text_extraction_skill",
        route_after_text_extraction,
        {
            "sandbox": "sandbox",
            "validator": "validator",
        },
    )
    graph_builder.add_conditional_edges(
        "tools",
        route_after_tools,
        {
            "assistant": "assistant",
            "text_extraction_skill": "text_extraction_skill",
        },
    )
    graph_builder.add_conditional_edges(
        "danger_tools_node",
        route_after_tools,
        {
            "assistant": "assistant",
            "text_extraction_skill": "text_extraction_skill",
        },
    )
    graph_builder.add_edge("sandbox", "validator")
    graph_builder.add_edge("validator", "finalizer")
    graph_builder.add_edge("finalizer", END)

    checkpointer = await _build_checkpointer_async(config, mcp_result.warnings)
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


def build_agent(config: AgentConfig) -> AgentRuntime:
    return asyncio.run(build_agent_async(config))
