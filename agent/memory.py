from __future__ import annotations

from model_providers.base import ChatMessage
from sumo_domain.preferences import UserPreferences
from sumo_domain.project_spec import ProjectContext


class SessionMemory:
    def __init__(self) -> None:
        self._messages: list[ChatMessage] = []

    def append_user_message(self, text: str) -> None:
        self._messages.append(ChatMessage(role="user", content=text))

    def append_agent_message(self, text: str) -> None:
        self._messages.append(ChatMessage(role="assistant", content=text))

    def recent_messages(self, limit: int = 10) -> list[ChatMessage]:
        return self._messages[-limit:]


class PreferenceContextBuilder:
    def build_system_context(self, preferences: UserPreferences, project: ProjectContext | None) -> str:
        project_line = "无当前项目。"
        if project and project.meta:
            project_line = f"当前项目: {project.meta.name}"
        extra = preferences.system_prompt_additions or "无额外偏好"
        return (
            f"默认场景={preferences.default_scenario_type}; "
            f"默认流量={preferences.default_flow_level}; "
            f"默认时长={preferences.default_duration}; "
            f"额外偏好={extra}; {project_line}"
        )
