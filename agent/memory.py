from __future__ import annotations

from model_providers.base import ChatMessage
from sumo_domain.preferences import UserPreferences
from sumo_domain.project_spec import ProjectContext


class SessionMemory:
    def __init__(self) -> None:
        self._messages: list[ChatMessage] = []
        self._tool_summaries: list[str] = []

    def append_user_message(self, text: str) -> None:
        self._messages.append(ChatMessage(role="user", content=text))

    def append_agent_message(self, text: str) -> None:
        self._messages.append(ChatMessage(role="assistant", content=text))

    def append_tool_summary(self, text: str) -> None:
        if text:
            self._tool_summaries.append(text)

    def recent_messages(self, limit: int = 8) -> list[ChatMessage]:
        return self._messages[-limit:]

    def recent_dialogue_text(self, limit: int = 8) -> str:
        recent = self.recent_messages(limit)
        if not recent:
            return ""
        role_map = {"user": "用户", "assistant": "通通", "system": "系统"}
        return " | ".join(
            f"{role_map.get(message.role, message.role)}: {message.content}" for message in recent
        )

    def last_tool_summary(self) -> str | None:
        if not self._tool_summaries:
            return None
        return self._tool_summaries[-1]


class PreferenceContextBuilder:
    def build_system_context(self, preferences: UserPreferences, project: ProjectContext | None) -> str:
        return self.build_project_summary(preferences, project)

    def build_project_summary(self, preferences: UserPreferences, project: ProjectContext | None) -> str:
        if project is None:
            return (
                f"当前没有打开项目。默认场景={preferences.default_scenario_type}，"
                f"默认流量={preferences.default_flow_level}，默认时长={preferences.default_duration} 秒。"
            )

        state = project.scenario_state
        if state is None:
            return f"当前项目 {project.meta.name} 已打开，但还没有完整的场景状态。"

        return (
            f"当前项目 {project.meta.name}：场景={state.scenario_type}，车道数={state.lane_count}，"
            f"道路长度={int(round(state.road_length))}m，限速={state.speed_limit * 3.6:.1f} km/h，"
            f"流量={state.flow_rate or state.flow_level}，时长={state.duration_seconds}s，步长={state.step_length}。"
        )
