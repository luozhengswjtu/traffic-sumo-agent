"""Model provider abstractions for TrafficAgent."""

from model_providers.base import BaseModelClient, ChatMessage, ModelResponse, ToolCall
from model_providers.openai_compatible import ModelClientFactory, OpenAICompatibleClient
