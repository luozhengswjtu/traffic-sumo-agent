from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(slots=True)
class RegisteredTool:
    name: str
    description: str
    schema: dict
    handler: Callable[[dict], dict]


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, RegisteredTool] = {}

    def register_tool(self, name: str, description: str, schema: dict, handler: Callable[[dict], dict]) -> None:
        self._tools[name] = RegisteredTool(name=name, description=description, schema=schema, handler=handler)

    def list_tool_schemas(self) -> list[dict]:
        return [tool.schema for tool in self._tools.values()]

    def invoke(self, name: str, arguments: dict) -> dict:
        if name not in self._tools:
            raise KeyError(f"未注册的工具: {name}")
        return self._tools[name].handler(arguments)

    def has_tool(self, name: str) -> bool:
        return name in self._tools
