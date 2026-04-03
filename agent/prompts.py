from __future__ import annotations

from sumo_domain.preferences import UserPreferences


def build_system_prompt(preferences: UserPreferences) -> str:
    extra = preferences.system_prompt_additions or "\u65e0"
    return (
        "\u4f60\u662f\u4ea4\u901a\u4eff\u771f Agent\u3002\u4f18\u5148\u8f93\u51fa\u53ef\u6267\u884c\u7684\u7ed3\u6784\u5316\u51b3\u7b56\uff0c\u800c\u4e0d\u662f\u6cdb\u6cdb\u5efa\u8bae\u3002"
        f" \u9ed8\u8ba4\u573a\u666f={preferences.default_scenario_type}\uff0c\u9ed8\u8ba4\u6d41\u91cf={preferences.default_flow_level}\uff0c"
        f"\u9ed8\u8ba4\u65f6\u957f={preferences.default_duration}\uff0c\u989d\u5916\u504f\u597d={extra}\u3002"
    )


def build_user_prompt(user_text: str, project_summary: str | None) -> str:
    summary = project_summary or "\u5f53\u524d\u6ca1\u6709\u9879\u76ee\u4e0a\u4e0b\u6587\u3002"
    return (
        "\u8bf7\u628a\u7528\u6237\u9700\u6c42\u89e3\u6790\u6210\u5355\u4e2a JSON \u5bf9\u8c61\uff0c\u4e0d\u8981\u8f93\u51fa\u989d\u5916\u8bf4\u660e\u6216 Markdown\u3002"
        "intent \u53ea\u80fd\u662f\uff1acreate_scenario\u3001edit_scenario\u3001run_simulation\u3001update_preferences\u3001"
        "summarize_project\u3001view_history\u3001unknown\u3002"
        "\u5982\u679c\u7528\u6237\u662f\u5728\u95f2\u804a\u3001\u95ee\u5019\u3001\u8ba9\u4f60\u81ea\u6211\u4ecb\u7ecd\uff0c\u6216\u9700\u6c42\u4e0d\u5c5e\u4e8e\u8fd9\u4e9b\u80fd\u529b\uff0cintent \u5fc5\u987b\u586b unknown\u3002"
        "\u5b57\u6bb5\u5305\u62ec\uff1aintent\u3001scenario_type\u3001lane_count\u3001duration_seconds\u3001step_length\u3001flow_level\u3001"
        "traffic_bias\u3001seed\u3001should_run_simulation\u3001preference_updates\u3002\u6ca1\u6709\u7684\u4fe1\u606f\u586b null\uff0c"
        "preference_updates \u6ca1\u6709\u66f4\u65b0\u65f6\u8fd4\u56de {}\u3002"
        f"\n\u9879\u76ee\u6458\u8981\uff1a{summary}\n\u7528\u6237\u8f93\u5165\uff1a{user_text}"
    )
