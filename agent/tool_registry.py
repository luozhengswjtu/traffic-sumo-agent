from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class RegisteredTool:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[[dict, dict[str, Any] | None], dict]


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, RegisteredTool] = {}

    def register_tool(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any],
        handler: Callable[[dict, dict[str, Any] | None], dict],
    ) -> None:
        self._tools[name] = RegisteredTool(
            name=name,
            description=description,
            parameters=parameters,
            handler=handler,
        )

    def list_tool_schemas(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                },
            }
            for tool in self._tools.values()
        ]

    def invoke(self, name: str, arguments: dict, runtime_context: dict[str, Any] | None = None) -> dict:
        if name not in self._tools:
            raise KeyError(f"未知工具: {name}")
        return self._tools[name].handler(arguments, runtime_context)

    def has_tool(self, name: str) -> bool:
        return name in self._tools

    def get_tool(self, name: str) -> RegisteredTool:
        if name not in self._tools:
            raise KeyError(f"未知工具: {name}")
        return self._tools[name]
