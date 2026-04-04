from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, Field


class ImageURL(BaseModel):
    url: str


class MessageContentPart(BaseModel):
    type: str
    text: str | None = None
    image_url: ImageURL | None = None

    @classmethod
    def text_part(cls, text: str) -> "MessageContentPart":
        return cls(type="text", text=text)

    @classmethod
    def image_part(cls, url: str) -> "MessageContentPart":
        return cls(type="image_url", image_url=ImageURL(url=url))

    def to_payload(self) -> dict:
        if self.type == "text":
            return {"type": "text", "text": self.text or ""}
        if self.type == "image_url" and self.image_url is not None:
            return {"type": "image_url", "image_url": self.image_url.model_dump()}
        return {"type": self.type}


class ChatMessage(BaseModel):
    role: str
    content: str | list[MessageContentPart]

    def text_content(self) -> str:
        if isinstance(self.content, str):
            return self.content
        parts: list[str] = []
        for part in self.content:
            if part.type == "text" and part.text:
                parts.append(part.text)
        return "\n".join(parts)


class ToolCall(BaseModel):
    name: str
    arguments: dict = Field(default_factory=dict)


class ModelResponse(BaseModel):
    text: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)


class BaseModelClient(Protocol):
    def chat(self, messages: list[ChatMessage], tools: list[dict] | None = None) -> ModelResponse:
        ...
