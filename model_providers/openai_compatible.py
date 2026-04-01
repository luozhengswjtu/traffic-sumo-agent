from __future__ import annotations

import json
from urllib import request
from urllib.error import HTTPError, URLError

from model_providers.base import BaseModelClient, ChatMessage, ModelResponse, ToolCall
from sumo_domain.preferences import ModelConfig


class OpenAICompatibleClient(BaseModelClient):
    def __init__(self, config: ModelConfig) -> None:
        self.config = config

    def chat(self, messages: list[ChatMessage], tools: list[dict] | None = None) -> ModelResponse:
        if not self.config.api_key:
            raise RuntimeError("当前未配置模型 API Key。")

        payload: dict = {
            "model": self.config.model,
            "messages": [message.model_dump() for message in messages],
            "temperature": self.config.temperature,
        }
        if tools:
            payload["tools"] = tools

        base_url = self.config.base_url.rstrip("/")
        url = f"{base_url}/chat/completions"
        data = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.config.api_key}",
        }

        http_request = request.Request(url=url, data=data, headers=headers, method="POST")
        try:
            with request.urlopen(http_request, timeout=self.config.timeout_seconds) as response:
                raw = response.read().decode("utf-8")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"模型接口返回错误：{exc.code} {detail}") from exc
        except URLError as exc:
            raise RuntimeError(f"无法连接模型接口：{exc.reason}") from exc

        body = json.loads(raw)
        message = body["choices"][0]["message"]
        content = self._extract_content(message.get("content"))
        tool_calls = [
            ToolCall(
                name=tool_call["function"]["name"],
                arguments=json.loads(tool_call["function"].get("arguments", "{}") or "{}"),
            )
            for tool_call in message.get("tool_calls", [])
        ]
        return ModelResponse(text=content, tool_calls=tool_calls)

    @staticmethod
    def _extract_content(content) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    parts.append(item.get("text", ""))
            return "\n".join(part for part in parts if part)
        return ""


class ModelClientFactory:
    def create(self, config: ModelConfig) -> BaseModelClient:
        return OpenAICompatibleClient(config)
