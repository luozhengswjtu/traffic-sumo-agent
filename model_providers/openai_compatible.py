from __future__ import annotations

import asyncio
import json
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from autogen_core import FunctionCall, Image
from autogen_core.models import AssistantMessage as AutoGenAssistantMessage
from autogen_core.models import ModelFamily, SystemMessage, UserMessage
from autogen_core.tools import ToolSchema
from autogen_ext.models.openai import OpenAIChatCompletionClient

from model_providers.base import BaseModelClient, ChatMessage, MessageContentPart, ModelResponse, ToolCall
from sumo_domain.preferences import ModelConfig


class OpenAICompatibleClient(BaseModelClient):
    def __init__(self, config: ModelConfig) -> None:
        self.config = config

    def chat(self, messages: list[ChatMessage], tools: list[dict] | None = None) -> ModelResponse:
        if not self.config.api_key:
            raise RuntimeError("当前未配置模型 API Key。")
        return asyncio.run(self._chat_async(messages, tools))

    async def _chat_async(self, messages: list[ChatMessage], tools: list[dict] | None = None) -> ModelResponse:
        client = build_autogen_chat_completion_client(self.config)
        try:
            response = await client.create(
                messages=_convert_messages(messages),
                tools=_convert_tools(tools),
            )
        except Exception as exc:
            raise RuntimeError(str(exc)) from exc
        finally:
            await client.close()
        return _convert_response(response.content)


class ModelClientFactory:
    def create(self, config: ModelConfig) -> BaseModelClient:
        return OpenAICompatibleClient(config)

    def create_raw_client(self, config: ModelConfig) -> OpenAIChatCompletionClient:
        return build_autogen_chat_completion_client(config)


def build_autogen_chat_completion_client(config: ModelConfig) -> OpenAIChatCompletionClient:
    return OpenAIChatCompletionClient(
        model=config.model,
        api_key=config.api_key,
        base_url=_normalize_base_url(config.base_url),
        timeout=float(config.timeout_seconds),
        temperature=_effective_temperature(config),
        extra_body=_extra_body(config),
        parallel_tool_calls=False,
        include_name_in_message=False,
        model_info={
            "vision": bool(config.supports_vision),
            "function_calling": True,
            "json_output": True,
            "structured_output": False,
            "family": ModelFamily.UNKNOWN,
        },
    )


def _normalize_base_url(base_url: str) -> str:
    cleaned = (base_url or "").strip().rstrip("/")
    if not cleaned:
        raise RuntimeError("模型 Base URL 不能为空。")
    parts = urlsplit(cleaned)
    path = parts.path.rstrip("/")
    if path.endswith("/chat/completions"):
        path = path[: -len("/chat/completions")]
    elif parts.netloc == "api.moonshot.cn" and not path:
        path = "/v1"
    return urlunsplit((parts.scheme, parts.netloc, path, parts.query, parts.fragment))


def _effective_temperature(config: ModelConfig) -> float | None:
    model_name = config.model.strip().lower()
    if model_name.startswith("kimi-k2.6"):
        return 0.6
    if model_name.startswith("kimi-k2.5"):
        return 1.0
    return config.temperature


def _extra_body(config: ModelConfig) -> dict[str, Any] | None:
    model_name = config.model.strip().lower()
    if model_name.startswith("kimi-k2.6"):
        return {"thinking": {"type": "disabled"}}
    return None


def _convert_messages(messages: list[ChatMessage]) -> list[Any]:
    converted: list[Any] = []
    for message in messages:
        if message.role == "system":
            converted.append(SystemMessage(content=message.text_content()))
            continue
        if message.role == "assistant":
            converted.append(AutoGenAssistantMessage(content=message.text_content(), source="assistant"))
            continue
        if isinstance(message.content, str):
            converted.append(UserMessage(content=message.content, source="user"))
            continue
        converted.append(UserMessage(content=_convert_content_parts(message.content), source="user"))
    return converted


def _convert_content_parts(parts: list[MessageContentPart]) -> list[str | Image]:
    converted: list[str | Image] = []
    for part in parts:
        if part.type == "text" and part.text is not None:
            converted.append(part.text)
        elif part.type == "image_url" and part.image_url is not None:
            converted.append(_convert_image(part.image_url.url))
    return converted


def _convert_image(url: str) -> Image:
    if url.startswith("data:"):
        try:
            _, encoded = url.split(",", 1)
        except ValueError as exc:
            raise RuntimeError("无效的 data URI 图片内容。") from exc
        return Image.from_base64(encoded)
    return Image.from_uri(url)


def _convert_tools(tools: list[dict] | None) -> list[ToolSchema]:
    converted: list[ToolSchema] = []
    for tool in tools or []:
        function = tool.get("function", tool)
        schema: ToolSchema = {"name": function["name"]}
        if function.get("description"):
            schema["description"] = function["description"]
        if function.get("parameters"):
            schema["parameters"] = function["parameters"]
        converted.append(schema)
    return converted


def _convert_response(content: Any) -> ModelResponse:
    if isinstance(content, str):
        return ModelResponse(text=content)
    if isinstance(content, list) and all(isinstance(item, FunctionCall) for item in content):
        return ModelResponse(
            tool_calls=[
                ToolCall(name=item.name, arguments=_parse_tool_arguments(item.arguments))
                for item in content
            ]
        )
    if hasattr(content, "model_dump"):
        dumped = content.model_dump(mode="json")
        return ModelResponse(text=json.dumps(dumped, ensure_ascii=False))
    if isinstance(content, dict):
        return ModelResponse(text=json.dumps(content, ensure_ascii=False))
    return ModelResponse(text=str(content or ""))


def _parse_tool_arguments(raw: str) -> dict:
    try:
        parsed = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}
