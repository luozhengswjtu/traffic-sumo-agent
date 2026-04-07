from __future__ import annotations

import json
from urllib import request
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit

from model_providers.base import BaseModelClient, ChatMessage, ModelResponse, ToolCall
from sumo_domain.preferences import ModelConfig


class OpenAICompatibleClient(BaseModelClient):
    def __init__(self, config: ModelConfig) -> None:
        self.config = config

    def chat(self, messages: list[ChatMessage], tools: list[dict] | None = None) -> ModelResponse:
        if not self.config.api_key:
            raise RuntimeError("\u5f53\u524d\u672a\u914d\u7f6e\u6a21\u578b API Key\u3002")

        payload: dict = {
            "model": self.config.model,
            "messages": [self._serialize_message(message) for message in messages],
        }
        temperature = self._effective_temperature()
        if temperature is not None:
            payload["temperature"] = temperature
        if tools:
            payload["tools"] = tools

        url = self._build_chat_completions_url()
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
            raise RuntimeError(f"\u6a21\u578b\u63a5\u53e3\u8fd4\u56de\u9519\u8bef\uff1a{exc.code} {detail}") from exc
        except URLError as exc:
            raise RuntimeError(f"\u65e0\u6cd5\u8fde\u63a5\u6a21\u578b\u63a5\u53e3\uff1a{exc.reason}") from exc

        body = json.loads(raw)
        message = body["choices"][0]["message"]
        content = self._extract_content(message.get("content"))
        tool_calls = [
            ToolCall(
                name=tool_call["function"]["name"],
                arguments=self._parse_tool_arguments(tool_call["function"].get("arguments", "{}")),
            )
            for tool_call in message.get("tool_calls", [])
        ]
        return ModelResponse(text=content, tool_calls=tool_calls)

    def _build_chat_completions_url(self) -> str:
        base_url = self.config.base_url.strip().rstrip("/")
        if not base_url:
            raise RuntimeError("\u6a21\u578b Base URL \u4e0d\u80fd\u4e3a\u7a7a\u3002")
        parts = urlsplit(base_url)
        path = parts.path.rstrip("/")
        if path.endswith("/chat/completions"):
            final_path = path
        elif path.endswith("/v1"):
            final_path = f"{path}/chat/completions"
        elif parts.netloc == "api.moonshot.cn" and not path:
            final_path = "/v1/chat/completions"
        else:
            final_path = f"{path}/chat/completions"
        return urlunsplit((parts.scheme, parts.netloc, final_path, parts.query, parts.fragment))

    def _effective_temperature(self) -> float | None:
        model_name = self.config.model.strip().lower()
        if model_name.startswith("kimi-k2.5"):
            # Moonshot's Kimi K2.5 only accepts temperature=1 on chat completions.
            return 1.0
        return self.config.temperature

    @staticmethod
    def _serialize_message(message: ChatMessage) -> dict:
        if isinstance(message.content, str):
            content: str | list[dict] = message.content
        else:
            content = [part.to_payload() for part in message.content]
        return {"role": message.role, "content": content}

    @staticmethod
    def _parse_tool_arguments(raw: str) -> dict:
        try:
            parsed = json.loads(raw or "{}")
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    @staticmethod
    def _extract_content(content) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    parts.append(str(item.get("text", "")))
            return "\n".join(part for part in parts if part)
        return ""


class ModelClientFactory:
    def create(self, config: ModelConfig) -> BaseModelClient:
        return OpenAICompatibleClient(config)
