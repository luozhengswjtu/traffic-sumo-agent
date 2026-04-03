from __future__ import annotations

from sumo_domain.preferences import UserPreferences


def _preferences_suffix(preferences: UserPreferences) -> str:
    extra = preferences.system_prompt_additions or "无"
    return (
        f"默认场景={preferences.default_scenario_type}，默认流量={preferences.default_flow_level}，"
        f"默认时长={preferences.default_duration}，额外偏好={extra}。"
    )


def build_parse_system_prompt(preferences: UserPreferences) -> str:
    return (
        "你是 TrafficAgent 的命令解析器。"
        "你的任务是把用户输入解析为结构化 JSON，用于交通仿真场景生成和编辑。"
        "只输出一个 JSON 对象，不要输出解释、不要输出代码块、不要输出额外文本。"
        f" {_preferences_suffix(preferences)}"
    )


def build_parse_user_prompt(user_text: str, project_summary: str | None) -> str:
    summary = project_summary or "当前没有项目上下文。"
    return (
        "请把用户需求解析成 JSON。\n"
        "允许字段包括：intent、scenario_type、lane_count、road_length、speed_limit、"
        "duration_seconds、step_length、flow_level、flow_rate、flow_multiplier、traffic_bias、seed、"
        "should_run_simulation、preference_updates、project_name。\n"
        "如果不是明确的仿真操作指令，请返回 {\"intent\": \"unknown\"}。\n"
        f"项目摘要：{summary}\n"
        f"用户输入：{user_text}"
    )


def build_chat_system_prompt(preferences: UserPreferences) -> str:
    return (
        "你是 TrafficAgent，面向交通仿真桌面应用的中文助手。"
        "当用户不是在下达仿真操作命令时，直接正常回答。"
        "回答简洁、直接，不要强行输出 JSON。"
        f" {_preferences_suffix(preferences)}"
    )


def build_chat_user_prompt(user_text: str, project_summary: str | None) -> str:
    summary = project_summary or "当前没有项目上下文。"
    return f"项目摘要：{summary}\n用户输入：{user_text}"
