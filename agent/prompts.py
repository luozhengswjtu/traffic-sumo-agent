from __future__ import annotations

from sumo_domain.preferences import UserPreferences

ASSISTANT_NAME = "通通"
NEWLINE = chr(10)
DOUBLE_NEWLINE = NEWLINE * 2


def _preferences_suffix(preferences: UserPreferences) -> str:
    extra = preferences.system_prompt_additions or "无"
    return (
        f"默认场景={preferences.default_scenario_type}，"
        f"默认流量={preferences.default_flow_level}，"
        f"默认时长={preferences.default_duration}，"
        f"额外偏好={extra}。"
    )


def build_assistant_system_prompt(preferences: UserPreferences) -> str:
    return (
        f"你是 TrafficAgent 桌面应用的中文代理 {ASSISTANT_NAME}。"
        "你的工作范围限定为 TrafficAgent 产品能力、当前项目上下文、SUMO 和交通仿真相关说明。"
        "普通问答直接用自然语言回答；可执行的工程或仿真需求要优先调用工具。"
        "如果问题超出这个范围，要明确说明你主要支持本产品和当前项目，不要冒充通用百科助手。"
        "当用户的意图是查看介绍、能力、当前项目、操作建议等非执行问题时，不要强行调工具。"
        "当用户要生成场景、修改参数、查看历史、查看项目摘要、更新偏好或运行仿真时，应当调用提供的 tool schema。"
        "回答要简洁、工程化、对用户友好。"
        f" {_preferences_suffix(preferences)}"
    )


def build_context_system_prompt(
    project_summary: str | None,
    recent_dialogue: str | None,
    last_tool_summary: str | None,
) -> str:
    project_line = project_summary or "当前没有项目上下文。"
    dialogue_line = recent_dialogue or "当前会话还没有更早的对话。"
    tool_line = last_tool_summary or "本会话还没有工具执行记录。"
    return NEWLINE.join(
        [
            "这是当前会话的额外上下文。",
            f"项目摘要：{project_line}",
            f"最近对话：{dialogue_line}",
            f"最近工具结果：{tool_line}",
        ]
    )


def build_result_system_prompt(preferences: UserPreferences) -> str:
    return (
        f"你是 {ASSISTANT_NAME}，需要根据工具执行结果给用户写最终说明。"
        "用自然中文总结，要交代你理解了什么、执行了哪些动作、当前项目发生了什么变化、还有哪些问题或下一步建议。"
        "不要输出 JSON，不要原封不动复读 tool arguments，要用用户看得懂的方式说明。"
        f" {_preferences_suffix(preferences)}"
    )


def build_result_user_prompt(
    user_text: str,
    project_summary: str | None,
    tool_summaries: list[str],
    issues: list[str],
) -> str:
    project_line = project_summary or "当前没有项目上下文。"
    tool_block = [f"- {item}" for item in tool_summaries] or ["- 本轮没有工具执行结果。"]
    issue_block = [f"- {item}" for item in issues] or ["- 无"]
    return NEWLINE.join(
        [
            f"用户原话：{user_text}",
            f"当前项目：{project_line}",
            "工具执行摘要：",
            *tool_block,
            "已知问题：",
            *issue_block,
        ]
    )


def build_intro_reply(project_summary: str | None) -> str:
    project_line = project_summary or "当前还没有打开项目。"
    return DOUBLE_NEWLINE.join(
        [
            (
                f"我是 {ASSISTANT_NAME}，负责 TrafficAgent 里的交通仿真协作。"
                "我可以帮你生成 SUMO 场景、修改车道、流量、时长、步长等参数，也可以查看当前项目摘要、操作历史，并在场景就绪后发起仿真。"
                "如果你直接说需求，我会先理解你的意图，再选择是直接回答还是调用工具。"
            ),
            f"当前你的项目上下文：{project_line}",
        ]
    )


def build_capability_reply(project_summary: str | None) -> str:
    project_line = project_summary or "当前还没有打开项目。"
    return NEWLINE.join(
        [
            f"{ASSISTANT_NAME} 主要做三类事情。",
            "1. 用自然语言解释 TrafficAgent 能做什么，并结合当前项目回答你的问题。",
            "2. 把你的工程指令转成可执行的工具调用，比如生成十字路口、调整流量、查看历史、运行仿真。",
            "3. 在执行完成后，把变更和结果整理成人话告诉你。",
            "",
            f"当前你的项目上下文：{project_line}",
        ]
    )


def build_how_to_reply(project_summary: str | None) -> str:
    project_line = project_summary or "当前还没有打开项目。"
    return NEWLINE.join(
        [
            "你可以直接用接近口语的方式提需求。",
            "- 生成场景：生成一个双向四车道十字路口，仿真 1800 秒。",
            "- 调整参数：把流量提高 30% 并运行。",
            "- 查看信息：当前项目是什么？ 或 看看最近 5 条历史。",
            "- 更新偏好：以后默认场景用十字路口，默认时长 1200 秒。",
            "",
            f"当前你的项目上下文：{project_line}",
        ]
    )
