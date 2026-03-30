from __future__ import annotations

import importlib
from typing import Iterable

from langchain_core.tools import BaseTool


class ToolLoadError(RuntimeError):
    pass


def _ensure_tools(values: Iterable[object], module_name: str) -> list[BaseTool]:
    tools: list[BaseTool] = []
    for value in values:
        if isinstance(value, BaseTool):
            tools.append(value)
            continue
        raise ToolLoadError(f"Module {module_name} exposed a non-BaseTool object: {type(value)!r}")
    return tools


def load_local_tools(module_names: list[str]) -> list[BaseTool]:
    loaded: list[BaseTool] = []

    for module_name in module_names:
        module = importlib.import_module(module_name)

        if hasattr(module, "get_tools"):
            result = module.get_tools()
            if not isinstance(result, list):
                result = list(result)
            loaded.extend(_ensure_tools(result, module_name))
            continue

        if hasattr(module, "TOOLS"):
            values = getattr(module, "TOOLS")
            if not isinstance(values, list):
                values = list(values)
            loaded.extend(_ensure_tools(values, module_name))
            continue

        raise ToolLoadError(
            f"Module {module_name} must expose get_tools() or TOOLS for tool loading."
        )

    return loaded
