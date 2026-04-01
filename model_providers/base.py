from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: str
    content: str


class ToolCall(BaseModel):
    name: str
    arguments: dict = Field(default_factory=dict)


class ModelResponse(BaseModel):
    text: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)


class BaseModelClient(Protocol):
    def chat(self, messages: list[ChatMessage], tools: list[dict] | None = None) -> ModelResponse:
        ...
