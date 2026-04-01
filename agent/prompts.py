from __future__ import annotations

from sumo_domain.preferences import UserPreferences


def build_system_prompt(preferences: UserPreferences) -> str:
    extra = preferences.system_prompt_additions or "无"
    return (
        "你是交通仿真 Agent。优先输出可执行的结构化决策，而不是泛泛建议。"
        f" 默认场景={preferences.default_scenario_type}，默认流量={preferences.default_flow_level}，"
        f"默认时长={preferences.default_duration}，额外偏好={extra}。"
    )


def build_user_prompt(user_text: str, project_summary: str | None) -> str:
    summary = project_summary or "当前没有项目上下文。"
    return (
        "请把用户需求解析成 JSON，字段包括：intent、scenario_type、lane_count、duration_seconds、"
        "step_length、flow_level、traffic_bias、seed、should_run_simulation、preference_updates。"
        f"\n项目摘要：{summary}\n用户输入：{user_text}"
    )
