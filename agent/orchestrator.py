from __future__ import annotations

import base64
import json
import mimetypes
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel, Field

from agent.autogen_bridge import AutoGenAssistantBridge, AutoGenToolRun
from agent.image_models import ImageAnalysisResult, ImageAnalysisStatus, IntersectionImageDraft, SUPPORTED_TOPOLOGIES
from agent.intents import UserIntent
from agent.memory import PreferenceContextBuilder, SessionMemory
from agent.prompts import (
    ASSISTANT_NAME,
    build_assistant_system_prompt,
    build_capability_reply,
    build_context_system_prompt,
    build_how_to_reply,
    build_image_analysis_system_prompt,
    build_image_analysis_user_prompt,
    build_image_patch_system_prompt,
    build_image_patch_user_prompt,
    build_intro_reply,
    build_result_system_prompt,
    build_result_user_prompt,
)
from agent.tool_registry import ToolRegistry
from model_providers.base import ChatMessage, MessageContentPart, ToolCall
from sumo_domain.preferences import ModelConfig, UserPreferences
from sumo_domain.project_spec import (
    DirectionalLaneConfig,
    ProjectContext,
    ProjectMeta,
    ProjectOperationRecord,
    ProjectScenarioState,
    RecentProjectItem,
)
from sumo_tools.config_generator import SimulationConfigRequest
from sumo_tools.network_generator import NetworkGenerationRequest
from sumo_tools.route_generator import RouteGenerationRequest


class ParsedCommand(BaseModel):
    intent: UserIntent = UserIntent.UNKNOWN
    scenario_type: str | None = None
    lane_count: int | None = None
    directional_lanes: DirectionalLaneConfig | None = None
    road_length: float | None = None
    lane_delta: int | None = None
    speed_limit: float | None = None
    duration_seconds: int | None = None
    step_length: float | None = None
    flow_level: str | None = None
    flow_rate: int | None = None
    flow_multiplier: float | None = None
    traffic_bias: str | None = None
    seed: int | None = None
    history_limit: int = 5
    reset_traffic_bias: bool = False
    reset_seed: bool = False
    reset_flow_to_default: bool = False
    reset_duration_to_default: bool = False
    reset_step_length_to_default: bool = False
    should_run_simulation: bool = False
    preference_updates: dict = Field(default_factory=dict)
    project_name: str | None = None


@dataclass(slots=True)
class AssistantProgress:
    stage: str
    message: str


@dataclass(slots=True)
class AssistantDecision:
    mode: str
    reply_text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    used_model: bool = False


@dataclass(slots=True)
class ToolExecutionSummary:
    tool_name: str
    summary: str
    issues: list[str] = field(default_factory=list)


class AgentExecutionResult(BaseModel):
    reply_text: str
    updated_project: ProjectContext | None = None
    generated_files: list[str] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)
    should_run_simulation: bool = False
    operation_summary: str | None = None
    before_state: dict | None = None
    after_state: dict | None = None
    history_record_id: int | None = None
    response_mode: str = "chat"
    assistant_name: str = ASSISTANT_NAME


class AgentOrchestrator:
    FLOW_LEVEL_MAP = {
        "low": 300,
        "medium": 600,
        "high": 1200,
        "very_high": 1800,
    }
    SCENARIO_LABELS = {
        "intersection": "十字路口",
        "t_junction": "T 字路口",
        "corridor": "直线路段",
    }
    BIAS_LABELS = {
        "north_south": "南北向",
        "east_west": "东西向",
        None: "无",
    }
    STATE_FIELD_LABELS = {
        "scenario_type": "场景类型",
        "lane_count": "车道数",
        "road_length": "道路长度",
        "speed_limit": "限速",
        "flow_level": "流量等级",
        "flow_rate": "流量",
        "traffic_bias": "交通偏向",
        "duration_seconds": "仿真时长",
        "step_length": "仿真步长",
        "seed": "随机种子",
    }
    TRACKED_INTENTS = {
        UserIntent.CREATE_SCENARIO,
        UserIntent.EDIT_SCENARIO,
        UserIntent.RUN_SIMULATION,
        UserIntent.UPDATE_PREFERENCES,
        UserIntent.SUMMARIZE_PROJECT,
    }

    def __init__(
        self,
        tool_registry: ToolRegistry,
        project_store,
        recent_store,
        history_store,
        config_store,
        network_generator,
        route_generator,
        config_generator,
        project_builder,
        validator,
        model_client_factory,
        get_model_config: Callable[[], ModelConfig],
        get_user_preferences: Callable[[], UserPreferences],
        set_user_preferences: Callable[[UserPreferences], None],
    ) -> None:
        self.tool_registry = tool_registry
        self.project_store = project_store
        self.recent_store = recent_store
        self.history_store = history_store
        self.config_store = config_store
        self.network_generator = network_generator
        self.route_generator = route_generator
        self.config_generator = config_generator
        self.project_builder = project_builder
        self.validator = validator
        self.model_client_factory = model_client_factory
        self.get_model_config = get_model_config
        self.get_user_preferences = get_user_preferences
        self.set_user_preferences = set_user_preferences
        self.memory = SessionMemory()
        self.preference_context_builder = PreferenceContextBuilder()
        self._last_model_error: str | None = None
        self.autogen_bridge = AutoGenAssistantBridge(
            tool_registry=self.tool_registry,
            model_client_factory=self.model_client_factory,
            get_model_config=self.get_model_config,
            normalize_tool_arguments=self._normalize_tool_arguments,
            format_error=self._format_model_error,
        )
        self._register_tools()

    def handle_user_message(
        self,
        text: str,
        project: ProjectContext | None,
        progress_callback: Callable[[AssistantProgress], None] | None = None,
    ) -> AgentExecutionResult:
        self.memory.append_user_message(text)
        self._last_model_error = None
        preferences = self.get_user_preferences()
        context_parts = self._build_context_parts(project, preferences)

        self._emit_progress(progress_callback, "\u7406\u89e3\u4e2d", f"{ASSISTANT_NAME} \u6b63\u5728\u7406\u89e3\u4f60\u7684\u9700\u6c42...")
        local_reply = self._build_local_chat_reply(text, project, context_parts["project_summary"])
        if local_reply is not None:
            result = AgentExecutionResult(
                reply_text=local_reply,
                updated_project=project,
                response_mode="chat",
                assistant_name=ASSISTANT_NAME,
            )
            self.memory.append_agent_message(result.reply_text)
            return result

        self._emit_progress(progress_callback, "\u89c4\u5212\u4e2d", f"{ASSISTANT_NAME} \u6b63\u5728\u901a\u8fc7 AutoGen \u89c4\u5212\u56de\u590d\u548c\u5de5\u5177...")
        autogen_result = self._run_with_autogen(text, project, context_parts)
        if autogen_result is not None:
            if autogen_result.tool_runs:
                self._emit_progress(progress_callback, "\u6267\u884c\u4e2d", f"{ASSISTANT_NAME} \u6b63\u5728\u6267\u884c AutoGen \u9009\u4e2d\u7684\u5de5\u5177...")
                tool_summaries, result = self._merge_autogen_tool_runs(autogen_result.tool_runs, project)
                for issue in autogen_result.issues:
                    if issue not in result.issues:
                        result.issues.append(issue)
                self._emit_progress(progress_callback, "\u6574\u7406\u7ed3\u679c", f"{ASSISTANT_NAME} \u6b63\u5728\u6574\u7406\u7ed3\u679c...")
                result.reply_text = self.summarize_result(text, result.updated_project or project, tool_summaries, result.issues)
                history_command = self._build_history_command(text, project, [item.tool_call for item in autogen_result.tool_runs])
                history_record = self._record_operation(history_command, text, project, result)
                if history_record is not None:
                    result.history_record_id = history_record.id
                    result.reply_text = chr(10).join([result.reply_text, "", f"\u5df2\u8bb0\u5f55\u5230\u64cd\u4f5c\u5386\u53f2\uff1a#{history_record.id}"])

                combined_summary = " | ".join(item.summary for item in tool_summaries if item.summary)
                if combined_summary:
                    self.memory.append_tool_summary(combined_summary)
                self.memory.append_agent_message(result.reply_text)
                return result

            if autogen_result.reply_text.strip():
                result = AgentExecutionResult(
                    reply_text=autogen_result.reply_text.strip(),
                    updated_project=project,
                    issues=list(autogen_result.issues),
                    response_mode="chat",
                    assistant_name=ASSISTANT_NAME,
                )
                self.memory.append_agent_message(result.reply_text)
                return result

        fallback_command = self._parse_command(text, project)
        tool_calls = self._plan_tools_with_rules(fallback_command)
        if tool_calls:
            self._emit_progress(progress_callback, "\u6267\u884c\u4e2d", f"{ASSISTANT_NAME} \u6b63\u5728\u6309\u672c\u5730\u89c4\u5219\u6267\u884c\u5de5\u5177...")
            tool_summaries, result = self.execute_tool_plan(tool_calls, project)
            if self._last_model_error:
                fallback_issue = f"AutoGen \u89c4\u5212\u5df2\u56de\u9000\u5230\u672c\u5730\u89c4\u5219\uff1a{self._last_model_error}"
                if fallback_issue not in result.issues:
                    result.issues.append(fallback_issue)
            self._emit_progress(progress_callback, "\u6574\u7406\u7ed3\u679c", f"{ASSISTANT_NAME} \u6b63\u5728\u6574\u7406\u7ed3\u679c...")
            result.reply_text = self.summarize_result(text, result.updated_project or project, tool_summaries, result.issues)
            history_command = self._build_history_command(text, project, tool_calls)
            history_record = self._record_operation(history_command, text, project, result)
            if history_record is not None:
                result.history_record_id = history_record.id
                result.reply_text = chr(10).join([result.reply_text, "", f"\u5df2\u8bb0\u5f55\u5230\u64cd\u4f5c\u5386\u53f2\uff1a#{history_record.id}"])
            combined_summary = " | ".join(item.summary for item in tool_summaries if item.summary)
            if combined_summary:
                self.memory.append_tool_summary(combined_summary)
            self.memory.append_agent_message(result.reply_text)
            return result

        issues: list[str] = []
        if self._last_model_error:
            issues.append(f"AutoGen \u89c4\u5212\u5df2\u56de\u9000\u5230\u672c\u5730\u89c4\u5219\uff1a{self._last_model_error}")
        result = AgentExecutionResult(
            reply_text=self._fallback_reply(fallback_command, project),
            updated_project=project,
            issues=issues,
            response_mode="chat",
            assistant_name=ASSISTANT_NAME,
        )
        self.memory.append_agent_message(result.reply_text)
        return result

    def detect_intent(self, text: str) -> UserIntent:
        lowered = text.lower()
        has_edit = any(token in text for token in ("\u6539\u6210", "\u4fee\u6539", "\u8c03\u6574", "\u63d0\u9ad8", "\u589e\u52a0", "\u964d\u4f4e", "\u51cf\u5c11", "\u8bbe\u4e3a", "\u8bbe\u7f6e", "\u66f4\u65b0", "\u6062\u590d\u9ed8\u8ba4", "\u53bb\u6389", "\u53d6\u6d88"))
        has_scenario = any(token in text for token in ("\u751f\u6210", "\u521b\u5efa", "\u65b0\u5efa", "\u5341\u5b57", "\u8def\u53e3", "t\u5b57", "T\u5b57", "\u4e01\u5b57", "\u8def\u6bb5", "\u8d70\u5eca"))
        has_param = any(token in text for token in ("\u6d41\u91cf", "\u6b65\u957f", "\u65f6\u957f", "\u8f66\u9053", "\u9650\u901f", "\u901f\u5ea6", "seed", "\u79cd\u5b50", "\u957f\u5ea6", "\u504f\u5411", "\u5357\u5317", "\u4e1c\u897f"))
        has_run = any(token in text for token in ("\u8fd0\u884c", "\u542f\u52a8", "\u5f00\u59cb\u4eff\u771f", "\u4eff\u771f\u4e00\u4e0b")) or "run" in lowered
        has_summary = any(token in text for token in ("\u5f53\u524d\u9879\u76ee", "\u9879\u76ee\u60c5\u51b5", "\u5f53\u524d\u573a\u666f", "\u573a\u666f\u6458\u8981", "\u603b\u7ed3\u5f53\u524d", "\u9879\u76ee\u662f\u4ec0\u4e48", "\u770b\u770b\u5f53\u524d"))
        has_history = any(token in text for token in ("\u64cd\u4f5c\u5386\u53f2", "\u6700\u8fd1\u53d8\u66f4", "\u67e5\u770b\u5386\u53f2", "\u5386\u53f2\u8bb0\u5f55", "\u6700\u8fd1\u64cd\u4f5c", "\u8ffd\u6eaf\u8bb0\u5f55"))
        has_pref_words = any(token in text for token in ("\u504f\u597d", "\u9ed8\u8ba4\u573a\u666f", "\u9ed8\u8ba4\u6d41\u91cf", "\u9ed8\u8ba4\u65f6\u957f", "\u4e60\u60ef"))
        if has_history:
            return UserIntent.VIEW_HISTORY
        if has_summary and not (has_edit or has_run or has_scenario):
            return UserIntent.SUMMARIZE_PROJECT
        if has_pref_words and not (has_scenario or has_param):
            return UserIntent.UPDATE_PREFERENCES
        if has_run and not (has_edit or has_scenario or has_param):
            return UserIntent.RUN_SIMULATION
        if has_edit and (has_param or has_scenario):
            return UserIntent.EDIT_SCENARIO
        if has_scenario:
            return UserIntent.CREATE_SCENARIO
        if has_param:
            return UserIntent.EDIT_SCENARIO
        if has_run:
            return UserIntent.RUN_SIMULATION
        return UserIntent.UNKNOWN

    def execute_tool_plan(
        self,
        tool_calls: list[ToolCall],
        project: ProjectContext | None,
    ) -> tuple[list[ToolExecutionSummary], AgentExecutionResult]:
        runtime_project = project
        merged = AgentExecutionResult(
            reply_text="",
            updated_project=project,
            response_mode="tool",
            assistant_name=ASSISTANT_NAME,
        )
        summaries: list[ToolExecutionSummary] = []

        for tool_call in tool_calls:
            runtime_context: dict[str, Any] = {"project": runtime_project}
            try:
                tool_result = self.tool_registry.invoke(tool_call.name, tool_call.arguments, runtime_context)
            except Exception as exc:
                message = f"工具 {tool_call.name} 执行失败：{self._format_model_error(str(exc) or exc.__class__.__name__)}"
                merged.issues.append(message)
                summaries.append(ToolExecutionSummary(tool_name=tool_call.name, summary=message, issues=[message]))
                continue

            summary_text = tool_result.get("operation_summary") or tool_result.get("reply_text") or f"已执行 {tool_call.name}"
            issues = [str(item) for item in tool_result.get("issues", [])]
            summaries.append(ToolExecutionSummary(tool_name=tool_call.name, summary=summary_text, issues=issues))

            updated_project = tool_result.get("updated_project")
            if isinstance(updated_project, dict):
                merged.updated_project = ProjectContext.model_validate(updated_project)
            elif isinstance(updated_project, ProjectContext):
                merged.updated_project = updated_project

            if merged.updated_project is not None:
                runtime_project = merged.updated_project
            if tool_result.get("generated_files"):
                merged.generated_files.extend(tool_result["generated_files"])
            if issues:
                merged.issues.extend(issues)
            if tool_result.get("should_run_simulation"):
                merged.should_run_simulation = True
            if tool_result.get("operation_summary"):
                merged.operation_summary = tool_result["operation_summary"]
            if tool_result.get("before_state") is not None:
                merged.before_state = tool_result["before_state"]
            if tool_result.get("after_state") is not None:
                merged.after_state = tool_result["after_state"]

        return summaries, merged

    def summarize_result(
        self,
        user_text: str,
        project: ProjectContext | None,
        tool_summaries: list[ToolExecutionSummary],
        issues: list[str],
    ) -> str:
        if not tool_summaries:
            command = self._parse_command(user_text, project)
            return self._fallback_reply(command, project)

        preferences = self.get_user_preferences()
        project_summary = self.preference_context_builder.build_project_summary(preferences, project)
        recent_dialogue = self.memory.recent_dialogue_text()
        last_tool_summary = " | ".join(item.summary for item in tool_summaries if item.summary)
        messages = [
            ChatMessage(role="system", content=build_result_system_prompt(preferences)),
            ChatMessage(role="system", content=build_context_system_prompt(project_summary, recent_dialogue, last_tool_summary)),
            ChatMessage(
                role="user",
                content=build_result_user_prompt(
                    user_text,
                    project_summary,
                    [item.summary for item in tool_summaries],
                    issues,
                ),
            ),
        ]
        try:
            client = self.model_client_factory.create(self.get_model_config())
            response = client.chat(messages)
            if response.text.strip():
                return response.text.strip()
        except Exception as exc:
            issues.append(f"结果整理已回退到本地模板：{self._format_model_error(str(exc) or exc.__class__.__name__)}")
        return self._fallback_tool_reply(user_text, project, tool_summaries, issues)

    @staticmethod
    def _emit_progress(
        progress_callback: Callable[[AssistantProgress], None] | None,
        stage: str,
        message: str,
    ) -> None:
        if progress_callback is None:
            return
        progress_callback(AssistantProgress(stage=stage, message=message))

    def _build_context_parts(self, project: ProjectContext | None, preferences: UserPreferences) -> dict[str, str | None]:
        return {
            "project_summary": self.preference_context_builder.build_project_summary(preferences, project),
            "recent_dialogue": self.memory.recent_dialogue_text(),
            "last_tool_summary": self.memory.last_tool_summary(),
        }

    def _run_with_autogen(
        self,
        text: str,
        project: ProjectContext | None,
        context_parts: dict[str, str | None],
    ):
        system_message = "\n\n".join(
            part
            for part in (
                build_assistant_system_prompt(self.get_user_preferences()),
                build_context_system_prompt(
                    context_parts.get("project_summary"),
                    context_parts.get("recent_dialogue"),
                    context_parts.get("last_tool_summary"),
                ),
                "\u4f18\u5148\u4f7f\u7528\u6700\u5c11\u5fc5\u8981\u5de5\u5177\u3002\u67e5\u770b\u9879\u76ee\u72b6\u6001\u3001\u5386\u53f2\u3001\u521b\u5efa\u6216\u4fee\u6539\u573a\u666f\u3001\u66f4\u65b0\u504f\u597d\u3001\u8fd0\u884c\u4eff\u771f\u65f6\uff0c\u8bf7\u8c03\u7528\u5bf9\u5e94\u5de5\u5177\u3002\u6240\u6709\u56de\u590d\u4f7f\u7528\u4e2d\u6587\u3002",
            )
            if part
        )
        try:
            return self.autogen_bridge.run(
                text=text,
                system_message=system_message,
                runtime_context={"project": project},
            )
        except Exception as exc:
            self._last_model_error = self._format_model_error(str(exc) or exc.__class__.__name__)
            return None

    def _merge_autogen_tool_runs(
        self,
        tool_runs: list[AutoGenToolRun],
        project: ProjectContext | None,
    ) -> tuple[list[ToolExecutionSummary], AgentExecutionResult]:
        merged = AgentExecutionResult(
            reply_text="",
            updated_project=project,
            response_mode="tool",
            assistant_name=ASSISTANT_NAME,
        )
        summaries: list[ToolExecutionSummary] = []
        for tool_run in tool_runs:
            tool_result = tool_run.result
            summary_text = tool_result.get("operation_summary") or tool_result.get("reply_text") or f"\u5df2\u6267\u884c {tool_run.tool_call.name}"
            issues = [str(item) for item in tool_result.get("issues", [])]
            summaries.append(ToolExecutionSummary(tool_name=tool_run.tool_call.name, summary=summary_text, issues=issues))

            updated_project = tool_result.get("updated_project")
            if isinstance(updated_project, dict):
                merged.updated_project = ProjectContext.model_validate(updated_project)
            elif isinstance(updated_project, ProjectContext):
                merged.updated_project = updated_project

            if tool_result.get("generated_files"):
                merged.generated_files.extend(tool_result["generated_files"])
            if issues:
                merged.issues.extend(issues)
            if tool_result.get("should_run_simulation"):
                merged.should_run_simulation = True
            if tool_result.get("operation_summary"):
                merged.operation_summary = tool_result["operation_summary"]
            if tool_result.get("before_state") is not None:
                merged.before_state = tool_result["before_state"]
            if tool_result.get("after_state") is not None:
                merged.after_state = tool_result["after_state"]

        return summaries, merged

    def _decide_response(
        self,
        text: str,
        project: ProjectContext | None,
        context_parts: dict[str, str | None],
    ) -> AssistantDecision:
        model_decision = self._decide_with_model(text, context_parts)
        if model_decision is not None:
            return model_decision
        command = self._parse_command(text, project)
        tool_calls = self._plan_tools_with_rules(command)
        issues: list[str] = []
        if self._last_model_error:
            issues.append(f"\u6a21\u578b\u89c4\u5212\u5df2\u56de\u9000\u5230\u672c\u5730\u89c4\u5219\uff1a{self._last_model_error}")
        if tool_calls:
            return AssistantDecision(mode="tool", tool_calls=tool_calls, issues=issues)
        return AssistantDecision(mode="chat", reply_text=self._fallback_reply(command, project), issues=issues)

    def _decide_with_model(self, text: str, context_parts: dict[str, str | None]) -> AssistantDecision | None:
        preferences = self.get_user_preferences()
        messages = [
            ChatMessage(role="system", content=build_assistant_system_prompt(preferences)),
            ChatMessage(
                role="system",
                content=build_context_system_prompt(
                    context_parts.get("project_summary"),
                    context_parts.get("recent_dialogue"),
                    context_parts.get("last_tool_summary"),
                ),
            ),
            ChatMessage(role="user", content=text),
        ]
        try:
            client = self.model_client_factory.create(self.get_model_config())
            response = client.chat(messages, tools=self.tool_registry.list_tool_schemas())
        except Exception as exc:
            self._last_model_error = self._format_model_error(str(exc) or exc.__class__.__name__)
            return None
        tool_calls, issues = self._coerce_tool_calls(response.tool_calls)
        if tool_calls:
            return AssistantDecision(mode="tool", tool_calls=tool_calls, issues=issues, used_model=True)
        if response.text.strip():
            return AssistantDecision(mode="chat", reply_text=response.text.strip(), issues=issues, used_model=True)
        return None

    def _coerce_tool_calls(self, tool_calls: list[ToolCall]) -> tuple[list[ToolCall], list[str]]:
        normalized_calls: list[ToolCall] = []
        issues: list[str] = []
        for tool_call in tool_calls:
            if not self.tool_registry.has_tool(tool_call.name):
                issues.append(f"\u5df2\u5ffd\u7565\u672a\u77e5\u5de5\u5177\uff1a{tool_call.name}")
                continue
            arguments = tool_call.arguments if isinstance(tool_call.arguments, dict) else {}
            normalized_calls.append(ToolCall(name=tool_call.name, arguments=self._normalize_tool_arguments(tool_call.name, arguments)))
        return normalized_calls, issues

    def _normalize_tool_arguments(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(arguments)
        for key in {
            "should_run_simulation",
            "reset_traffic_bias",
            "reset_seed",
            "reset_flow_to_default",
            "reset_duration_to_default",
            "reset_step_length_to_default",
        }:
            value = normalized.get(key)
            if value is None:
                normalized.pop(key, None)
            else:
                normalized[key] = bool(value)

        if tool_name == "generate_scenario":
            if normalized.get("speed_limit_kmh") is not None and normalized.get("speed_limit") is None:
                try:
                    normalized["speed_limit"] = round(float(normalized["speed_limit_kmh"]) / 3.6, 2)
                except (TypeError, ValueError):
                    normalized.pop("speed_limit_kmh", None)
            elif normalized.get("speed_limit") is not None:
                try:
                    speed_limit = float(normalized["speed_limit"])
                    normalized["speed_limit"] = round(speed_limit / 3.6, 2) if speed_limit > 40 else speed_limit
                except (TypeError, ValueError):
                    normalized.pop("speed_limit", None)

            if normalized.get("flow_multiplier") is not None:
                try:
                    flow_multiplier = float(normalized["flow_multiplier"])
                    normalized["flow_multiplier"] = 1.0 + flow_multiplier / 100.0 if flow_multiplier > 5 else flow_multiplier
                except (TypeError, ValueError):
                    normalized.pop("flow_multiplier", None)

            for key in ("lane_count", "lane_delta", "duration_seconds", "flow_rate", "seed"):
                if normalized.get(key) is None:
                    continue
                try:
                    normalized[key] = int(normalized[key])
                except (TypeError, ValueError):
                    normalized.pop(key, None)

            for key in ("road_length", "step_length"):
                if normalized.get(key) is None:
                    continue
                try:
                    normalized[key] = float(normalized[key])
                except (TypeError, ValueError):
                    normalized.pop(key, None)

            directional_lanes = self._coerce_directional_lanes(normalized.get("directional_lanes"))
            if directional_lanes.has_any():
                normalized["directional_lanes"] = directional_lanes.model_dump(exclude_none=True)
                normalized["lane_count"] = directional_lanes.effective_lane_count(
                    normalized.get("scenario_type") or "intersection",
                    int(normalized.get("lane_count") or 2),
                )
            else:
                normalized.pop("directional_lanes", None)

        if tool_name == "show_history" and normalized.get("limit") is not None:
            try:
                normalized["limit"] = int(normalized["limit"])
            except (TypeError, ValueError):
                normalized.pop("limit", None)

        return {key: value for key, value in normalized.items() if value is not None and value != ""}

    def _build_history_command(
        self,
        text: str,
        project: ProjectContext | None,
        tool_calls: list[ToolCall],
    ) -> ParsedCommand:
        command = self._parse_command(text, project)
        if command.intent != UserIntent.UNKNOWN:
            return command
        for tool_call in tool_calls:
            args = self._normalize_tool_arguments(tool_call.name, tool_call.arguments)
            if tool_call.name == "generate_scenario":
                intent = UserIntent.EDIT_SCENARIO if project is not None else UserIntent.CREATE_SCENARIO
                return ParsedCommand(
                    intent=intent,
                    scenario_type=args.get("scenario_type"),
                    lane_count=args.get("lane_count"),
                    directional_lanes=self._coerce_directional_lanes(args.get("directional_lanes")),
                    road_length=args.get("road_length"),
                    speed_limit=args.get("speed_limit"),
                    duration_seconds=args.get("duration_seconds"),
                    step_length=args.get("step_length"),
                    flow_level=args.get("flow_level"),
                    flow_rate=args.get("flow_rate"),
                    flow_multiplier=args.get("flow_multiplier"),
                    traffic_bias=args.get("traffic_bias"),
                    seed=args.get("seed"),
                    should_run_simulation=bool(args.get("should_run_simulation")),
                )
            if tool_call.name == "update_preferences":
                return ParsedCommand(intent=UserIntent.UPDATE_PREFERENCES, preference_updates=args)
            if tool_call.name == "summarize_project":
                return ParsedCommand(intent=UserIntent.SUMMARIZE_PROJECT)
            if tool_call.name == "show_history":
                return ParsedCommand(intent=UserIntent.VIEW_HISTORY, history_limit=int(args.get("limit", 5)))
            if tool_call.name == "request_run":
                return ParsedCommand(intent=UserIntent.RUN_SIMULATION, should_run_simulation=True)
        return command

    def _plan_tools_with_rules(self, command: ParsedCommand) -> list[ToolCall]:
        if command.intent in {UserIntent.CREATE_SCENARIO, UserIntent.EDIT_SCENARIO}:
            directional_lanes = command.directional_lanes.model_dump(exclude_none=True) if command.directional_lanes and command.directional_lanes.has_any() else None
            arguments = {
                key: value
                for key, value in {
                    "scenario_type": command.scenario_type,
                    "lane_count": command.lane_count,
                    "directional_lanes": directional_lanes,
                    "lane_delta": command.lane_delta,
                    "road_length": command.road_length,
                    "speed_limit": command.speed_limit,
                    "duration_seconds": command.duration_seconds,
                    "step_length": command.step_length,
                    "flow_level": command.flow_level,
                    "flow_rate": command.flow_rate,
                    "flow_multiplier": command.flow_multiplier,
                    "traffic_bias": command.traffic_bias,
                    "seed": command.seed,
                    "reset_traffic_bias": command.reset_traffic_bias,
                    "reset_seed": command.reset_seed,
                    "reset_flow_to_default": command.reset_flow_to_default,
                    "reset_duration_to_default": command.reset_duration_to_default,
                    "reset_step_length_to_default": command.reset_step_length_to_default,
                    "should_run_simulation": command.should_run_simulation,
                    "project_name": command.project_name,
                }.items()
                if value not in (None, False, "", {})
            }
            return [ToolCall(name="generate_scenario", arguments=arguments)]
        if command.intent == UserIntent.UPDATE_PREFERENCES and command.preference_updates:
            return [ToolCall(name="update_preferences", arguments=dict(command.preference_updates))]
        if command.intent == UserIntent.RUN_SIMULATION:
            return [ToolCall(name="request_run", arguments={})]
        if command.intent == UserIntent.SUMMARIZE_PROJECT:
            return [ToolCall(name="summarize_project", arguments={})]
        if command.intent == UserIntent.VIEW_HISTORY:
            return [ToolCall(name="show_history", arguments={"limit": command.history_limit})]
        return []

    def _register_tools(self) -> None:
        directional_lane_schema = {
            edge_id: {"type": "integer", "minimum": 1, "maximum": 8}
            for edge_id in DirectionalLaneConfig.EDGE_ORDER
        }
        self.tool_registry.register_tool(
            "generate_scenario",
            "??????? SUMO ?????????????????????????????????????????????????????",
            {
                "type": "object",
                "properties": {
                    "scenario_type": {"type": "string", "enum": ["intersection", "t_junction", "corridor"]},
                    "lane_count": {"type": "integer", "minimum": 1},
                    "directional_lanes": {
                        "type": "object",
                        "properties": directional_lane_schema,
                        "additionalProperties": False,
                    },
                    "lane_delta": {"type": "integer"},
                    "road_length": {"type": "number", "minimum": 20},
                    "speed_limit_kmh": {"type": "number", "minimum": 5},
                    "speed_limit": {"type": "number", "minimum": 1},
                    "duration_seconds": {"type": "integer", "minimum": 30},
                    "step_length": {"type": "number", "minimum": 0.1},
                    "flow_level": {"type": "string", "enum": ["low", "medium", "high", "very_high"]},
                    "flow_rate": {"type": "integer", "minimum": 1},
                    "flow_multiplier": {"type": "number", "minimum": 0.05},
                    "traffic_bias": {"type": "string", "enum": ["north_south", "east_west"]},
                    "seed": {"type": "integer", "minimum": 0},
                    "reset_traffic_bias": {"type": "boolean"},
                    "reset_seed": {"type": "boolean"},
                    "reset_flow_to_default": {"type": "boolean"},
                    "reset_duration_to_default": {"type": "boolean"},
                    "reset_step_length_to_default": {"type": "boolean"},
                    "should_run_simulation": {"type": "boolean"},
                    "project_name": {"type": "string"},
                },
                "additionalProperties": False,
            },
            self._tool_generate_scenario,
        )
        self.tool_registry.register_tool(
            "update_preferences",
            "????????????????????????????????????",
            {
                "type": "object",
                "properties": {
                    "default_scenario_type": {"type": "string", "enum": ["intersection", "t_junction", "corridor"]},
                    "default_flow_level": {"type": "string", "enum": ["low", "medium", "high", "very_high"]},
                    "default_duration": {"type": "integer", "minimum": 30},
                    "system_prompt_additions": {"type": "string"},
                },
                "additionalProperties": False,
            },
            self._tool_update_preferences,
        )
        self.tool_registry.register_tool("request_run", "???????????", {"type": "object", "properties": {}, "additionalProperties": False}, self._tool_request_run)
        self.tool_registry.register_tool("summarize_project", "?????????", {"type": "object", "properties": {}, "additionalProperties": False}, self._tool_summarize_project)
        self.tool_registry.register_tool(
            "show_history",
            "??????????",
            {"type": "object", "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 20}}, "additionalProperties": False},
            self._tool_show_history,
        )

    def _build_local_chat_reply(self, text: str, project: ProjectContext | None, project_summary: str | None) -> str | None:
        lowered = text.lower().strip()
        if any(token in text for token in ("\u4ecb\u7ecd\u4f60\u81ea\u5df1", "\u81ea\u6211\u4ecb\u7ecd", "\u4f60\u662f\u8c01", "\u4f60\u53eb", "\u4ecb\u7ecd\u4e00\u4e0b\u81ea\u5df1")):
            return build_intro_reply(project_summary)
        if any(token in text for token in ("\u4f60\u80fd\u505a\u4ec0\u4e48", "\u6709\u4ec0\u4e48\u7528", "\u53ef\u4ee5\u505a\u4ec0\u4e48", "\u80fd\u5e2e\u6211\u505a\u4ec0\u4e48", "\u652f\u6301\u4ec0\u4e48")):
            return build_capability_reply(project_summary)
        if any(token in text for token in ("\u600e\u4e48\u7528", "\u600e\u4e48\u751f\u6210", "\u5982\u4f55\u751f\u6210", "\u600e\u4e48\u521b\u5efa", "\u7ed9\u6211\u4e2a\u793a\u4f8b", "\u7ed9\u6211\u51e0\u4e2a\u4f8b\u5b50", "\u600e\u4e48\u64cd\u4f5c", "\u600e\u4e48\u4e0a\u4f20\u56fe\u7247")) or lowered in {"help", "usage"}:
            return build_how_to_reply(project_summary)
        if any(token in text for token in ("\u5f53\u524d\u9879\u76ee", "\u5f53\u524d\u573a\u666f", "\u9879\u76ee\u6458\u8981", "\u73b0\u5728\u662f\u4ec0\u4e48\u573a\u666f", "\u9879\u76ee\u662f\u4ec0\u4e48")):
            if project is None:
                return "\u5f53\u524d\u8fd8\u6ca1\u6709\u6253\u5f00\u9879\u76ee\u3002\u4f60\u53ef\u4ee5\u5148\u8ba9\u6211\u751f\u6210\u4e00\u4e2a\u573a\u666f\uff0c\u6216\u8005\u5148\u65b0\u5efa\u5e76\u52a0\u8f7d\u9879\u76ee\u3002"
            state = self._derive_scenario_state(project, self.get_user_preferences())
            return self._format_project_summary(project, state)
        return None

    def _tool_generate_scenario(self, arguments: dict, runtime_context: dict[str, Any] | None = None) -> dict:
        project_context = None
        if runtime_context and runtime_context.get("project") is not None:
            runtime_project = runtime_context["project"]
            project_context = runtime_project if isinstance(runtime_project, ProjectContext) else ProjectContext.model_validate(runtime_project)

        arguments = self._normalize_tool_arguments("generate_scenario", arguments)
        command = ParsedCommand(
            intent=UserIntent.EDIT_SCENARIO if project_context is not None else UserIntent.CREATE_SCENARIO,
            scenario_type=arguments.get("scenario_type"),
            lane_count=arguments.get("lane_count"),
            directional_lanes=self._coerce_directional_lanes(arguments.get("directional_lanes")),
            lane_delta=arguments.get("lane_delta"),
            road_length=arguments.get("road_length"),
            speed_limit=arguments.get("speed_limit"),
            duration_seconds=arguments.get("duration_seconds"),
            step_length=arguments.get("step_length"),
            flow_level=arguments.get("flow_level"),
            flow_rate=arguments.get("flow_rate"),
            flow_multiplier=arguments.get("flow_multiplier"),
            traffic_bias=arguments.get("traffic_bias"),
            seed=arguments.get("seed"),
            reset_traffic_bias=bool(arguments.get("reset_traffic_bias", False)),
            reset_seed=bool(arguments.get("reset_seed", False)),
            reset_flow_to_default=bool(arguments.get("reset_flow_to_default", False)),
            reset_duration_to_default=bool(arguments.get("reset_duration_to_default", False)),
            reset_step_length_to_default=bool(arguments.get("reset_step_length_to_default", False)),
            should_run_simulation=bool(arguments.get("should_run_simulation", False)),
            project_name=arguments.get("project_name"),
        )

        preferences = self.get_user_preferences()
        meta = project_context.meta if project_context else self._create_default_project_meta(command)
        base_context = project_context or ProjectContext(meta=meta)
        base_state = self._derive_scenario_state(base_context, preferences)

        if command.intent == UserIntent.EDIT_SCENARIO and not self._has_edit_payload(command):
            message = "?????????????????????????????????? 3 ??????? 30%????? 1200 ??"
            return {
                "reply_text": message,
                "updated_project": project_context.model_dump(mode="json") if project_context else None,
                "issues": ["?????????????"],
                "operation_summary": "??????????????",
                "before_state": base_state.model_dump(mode="json"),
                "after_state": base_state.model_dump(mode="json"),
            }

        next_state = self._apply_command_to_state(base_state, command, preferences)
        network = self.network_generator.generate(
            NetworkGenerationRequest(
                scenario_type=next_state.scenario_type,
                lane_count=next_state.lane_count,
                directional_lanes=next_state.directional_lanes,
                road_length=next_state.road_length,
                speed_limit=next_state.speed_limit,
            )
        )
        routes = self.route_generator.generate_routes(
            network,
            RouteGenerationRequest(
                flow_level=next_state.flow_level,
                flow_rate=next_state.flow_rate,
                duration_seconds=next_state.duration_seconds,
                traffic_bias=next_state.traffic_bias,
            ),
        )
        simulation = self.config_generator.build_simulation_spec(
            Path(meta.project_dir),
            SimulationConfigRequest(
                duration_seconds=next_state.duration_seconds,
                step_length=next_state.step_length,
                seed=next_state.seed,
            ),
        )
        updated_context = ProjectContext(meta=meta, network=network, routes=routes, simulation=simulation, scenario_state=next_state)
        build_result = self.project_builder.build_project(updated_context)
        issue_texts = [f"{issue.level}: {issue.message}" for issue in build_result.issues]
        has_build_errors = any(issue.level == "error" for issue in build_result.issues)

        operation_summary = self._build_state_change_summary(base_state if project_context else None, next_state)
        detail_summary = self._format_project_summary(updated_context, next_state)
        reply_prefix = "??????" if has_build_errors else "?????"
        reply_text = chr(10).join([reply_prefix, operation_summary, "", detail_summary])
        return {
            "reply_text": reply_text,
            "updated_project": updated_context.model_dump(mode="json"),
            "generated_files": [str(path) for path in build_result.generated_files],
            "issues": issue_texts,
            "should_run_simulation": command.should_run_simulation and not has_build_errors,
            "operation_summary": operation_summary,
            "before_state": base_state.model_dump(mode="json") if project_context else None,
            "after_state": next_state.model_dump(mode="json"),
        }

    def _tool_update_preferences(self, arguments: dict, runtime_context: dict[str, Any] | None = None) -> dict:
        current = self.get_user_preferences()
        updates = {key: value for key, value in arguments.items() if key in {"default_scenario_type", "default_flow_level", "default_duration", "system_prompt_additions"} and value is not None}
        if not updates:
            return {"reply_text": "\u8fd9\u6b21\u6ca1\u6709\u8bc6\u522b\u5230\u53ef\u66f4\u65b0\u7684\u504f\u597d\u5b57\u6bb5\u3002\u652f\u6301\u9ed8\u8ba4\u573a\u666f\u3001\u9ed8\u8ba4\u6d41\u91cf\u3001\u9ed8\u8ba4\u65f6\u957f\u548c\u989d\u5916\u63d0\u793a\u8bcd\u3002", "issues": []}
        updated = current.model_copy(update=updates)
        self.config_store.save_user_preferences(updated)
        self.set_user_preferences(updated)
        confirmation_lines = [f"- {key}: {getattr(current, key)} -> {value}" for key, value in updates.items()]
        operation_summary = chr(10).join(confirmation_lines)
        return {"reply_text": chr(10).join(["\u504f\u597d\u5df2\u66f4\u65b0\uff1a", operation_summary]), "issues": [], "operation_summary": operation_summary}

    def _tool_request_run(self, arguments: dict, runtime_context: dict[str, Any] | None = None) -> dict:
        project_context = None
        if runtime_context and runtime_context.get("project") is not None:
            runtime_project = runtime_context["project"]
            project_context = runtime_project if isinstance(runtime_project, ProjectContext) else ProjectContext.model_validate(runtime_project)
        if project_context is None:
            return {"reply_text": "\u5f53\u524d\u6ca1\u6709\u9879\u76ee\u4e0a\u4e0b\u6587\u3002\u8bf7\u5148\u751f\u6210\u573a\u666f\u6216\u521b\u5efa\u9879\u76ee\u540e\u518d\u8fd0\u884c\u3002", "issues": [], "operation_summary": "\u8fd0\u884c\u8bf7\u6c42\u5931\u8d25\uff1a\u7f3a\u5c11\u9879\u76ee\u4e0a\u4e0b\u6587\u3002"}
        operation_summary = f"\u8bf7\u6c42\u8fd0\u884c\u9879\u76ee {project_context.meta.name}\u3002"
        return {"reply_text": chr(10).join(["\u8fd0\u884c\u786e\u8ba4\uff1a", f"- \u5f53\u524d\u9879\u76ee\uff1a{project_context.meta.name}", "- \u72b6\u6001\uff1a\u5df2\u63a5\u53d7\u8fd0\u884c\u8bf7\u6c42\u3002"]), "should_run_simulation": True, "issues": [], "operation_summary": operation_summary, "before_state": project_context.scenario_state.model_dump(mode="json") if project_context.scenario_state else None, "after_state": project_context.scenario_state.model_dump(mode="json") if project_context.scenario_state else None}

    def _tool_summarize_project(self, arguments: dict, runtime_context: dict[str, Any] | None = None) -> dict:
        project = None
        if runtime_context and runtime_context.get("project") is not None:
            runtime_project = runtime_context["project"]
            project = runtime_project if isinstance(runtime_project, ProjectContext) else ProjectContext.model_validate(runtime_project)
        if project is None:
            return {"reply_text": "\u5f53\u524d\u6ca1\u6709\u9879\u76ee\u4e0a\u4e0b\u6587\u3002\u8bf7\u5148\u751f\u6210\u573a\u666f\u6216\u521b\u5efa\u9879\u76ee\u3002", "issues": []}
        state = self._derive_scenario_state(project, self.get_user_preferences())
        operation_summary = f"\u67e5\u770b\u9879\u76ee\u6458\u8981\uff1a{project.meta.name}"
        return {"reply_text": self._format_project_summary(project, state), "updated_project": project.model_dump(mode="json"), "issues": [], "operation_summary": operation_summary, "before_state": state.model_dump(mode="json"), "after_state": state.model_dump(mode="json")}

    def _tool_show_history(self, arguments: dict, runtime_context: dict[str, Any] | None = None) -> dict:
        project = None
        if runtime_context and runtime_context.get("project") is not None:
            runtime_project = runtime_context["project"]
            project = runtime_project if isinstance(runtime_project, ProjectContext) else ProjectContext.model_validate(runtime_project)
        limit = int(arguments.get("limit", 5))
        records = self.history_store.list_recent(project_dir=project.meta.project_dir if project else None, limit=limit)
        if not records:
            return {"reply_text": "\u5f53\u524d\u8fd8\u6ca1\u6709\u53ef\u8ffd\u6eaf\u7684\u64cd\u4f5c\u5386\u53f2\u3002", "issues": []}
        lines = [f"\u6700\u8fd1 {len(records)} \u6761\u64cd\u4f5c\u5386\u53f2" + (f"\uff08\u9879\u76ee\uff1a{project.meta.name}\uff09" if project else "")]
        for index, record in enumerate(records, start=1):
            created_at = record.created_at.strftime("%Y-%m-%d %H:%M:%S")
            lines.append(f"{index}. [{created_at}] {record.intent}")
            lines.append(f"\u7528\u6237\u6d88\u606f\uff1a{record.user_message}")
            lines.append(f"\u53d8\u66f4\u6458\u8981\uff1a{record.change_summary}")
        return {"reply_text": chr(10).join(lines), "issues": [], "operation_summary": lines[0]}

    def _derive_scenario_state(self, project: ProjectContext, preferences: UserPreferences) -> ProjectScenarioState:
        if project.scenario_state is not None:
            return project.scenario_state

        scenario_type = project.network.scenario_type if project.network else preferences.default_scenario_type
        directional_data = {
            edge.id: edge.num_lanes
            for edge in (project.network.edges if project.network else [])
            if edge.id in DirectionalLaneConfig.EDGE_ORDER
        }
        directional_lanes = DirectionalLaneConfig(**directional_data)
        lane_count = directional_lanes.effective_lane_count(scenario_type, 2) if directional_lanes.has_any() else 2
        road_length = 200.0
        if project.network and project.network.edges:
            first_length = project.network.edges[0].length or 100.0
            road_length = float(first_length) * 2.0
        speed_limit = project.network.edges[0].speed if project.network and project.network.edges else 13.89
        duration_seconds = project.simulation.end_time if project.simulation else preferences.default_duration
        step_length = project.simulation.step_length if project.simulation else 1.0
        seed = project.simulation.seed if project.simulation else None
        flow_rate = None
        if project.routes and project.routes.flows:
            flow_rate = int(round(sum(flow.vehs_per_hour for flow in project.routes.flows) / len(project.routes.flows)))
        flow_level = self._infer_flow_level(flow_rate or self.FLOW_LEVEL_MAP.get(preferences.default_flow_level, 600))
        traffic_bias = self._infer_traffic_bias(project)
        return ProjectScenarioState(
            scenario_type=scenario_type,
            lane_count=lane_count,
            directional_lanes=directional_lanes,
            road_length=road_length,
            speed_limit=speed_limit,
            flow_level=flow_level,
            flow_rate=flow_rate,
            traffic_bias=traffic_bias,
            duration_seconds=duration_seconds,
            step_length=step_length,
            seed=seed,
        )

    def _apply_command_to_state(self, base: ProjectScenarioState, command: ParsedCommand, preferences: UserPreferences) -> ProjectScenarioState:
        default_flow_rate = self.FLOW_LEVEL_MAP.get(preferences.default_flow_level, self.FLOW_LEVEL_MAP["medium"])
        current_flow_rate = base.flow_rate or self.FLOW_LEVEL_MAP.get(base.flow_level, default_flow_rate)

        if command.reset_flow_to_default:
            flow_level = preferences.default_flow_level
            flow_rate = default_flow_rate
        elif command.flow_level is not None:
            flow_level = command.flow_level
            flow_rate = self.FLOW_LEVEL_MAP.get(flow_level, current_flow_rate)
        else:
            flow_level = base.flow_level
            flow_rate = current_flow_rate

        if command.flow_rate is not None:
            flow_rate = command.flow_rate
            flow_level = self._infer_flow_level(flow_rate)
        if command.flow_multiplier is not None:
            flow_rate = max(1, int(round(flow_rate * command.flow_multiplier)))
            flow_level = self._infer_flow_level(flow_rate)

        traffic_bias = None if command.reset_traffic_bias else (command.traffic_bias if command.traffic_bias is not None else base.traffic_bias)
        seed = None if command.reset_seed else (command.seed if command.seed is not None else base.seed)
        duration_seconds = preferences.default_duration if command.reset_duration_to_default else (command.duration_seconds or base.duration_seconds)
        step_length = 1.0 if command.reset_step_length_to_default else (command.step_length or base.step_length)

        scenario_type = command.scenario_type or base.scenario_type
        lane_count = command.lane_count or base.lane_count
        if command.lane_delta is not None:
            lane_count = max(1, base.lane_count + command.lane_delta)

        directional_lanes = base.directional_lanes.model_copy(deep=True)
        if command.directional_lanes and command.directional_lanes.has_any():
            directional_lanes = self._coerce_directional_lanes(command.directional_lanes)
            lane_count = directional_lanes.effective_lane_count(scenario_type, lane_count)
        elif directional_lanes.has_any() and (command.lane_count is not None or command.lane_delta is not None or command.scenario_type is not None):
            directional_lanes = directional_lanes.merged_with_fallback(scenario_type, lane_count)

        return ProjectScenarioState(
            scenario_type=scenario_type,
            lane_count=lane_count,
            directional_lanes=directional_lanes,
            road_length=command.road_length or base.road_length,
            speed_limit=command.speed_limit or base.speed_limit,
            flow_level=flow_level,
            flow_rate=flow_rate,
            traffic_bias=traffic_bias,
            duration_seconds=duration_seconds,
            step_length=step_length,
            seed=seed,
        )

    def _create_default_project_meta(self, command: ParsedCommand) -> ProjectMeta:
        base_name = command.project_name or command.scenario_type or "traffic_agent"
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        meta = self.project_store.create_project(f"{base_name}_{timestamp}")
        self.recent_store.add_recent_project(RecentProjectItem(name=meta.name, project_dir=str(meta.project_dir), last_opened_at=datetime.now()))
        return meta

    def _parse_command(self, text: str, project: ProjectContext | None) -> ParsedCommand:
        return self._parse_with_rules(text, project)

    def _parse_with_model(self, text: str, project: ProjectContext | None) -> ParsedCommand | None:
        return None

    def _parse_with_rules(self, text: str, project: ProjectContext | None = None) -> ParsedCommand:
        command = ParsedCommand(intent=self.detect_intent(text))
        base_state = self._derive_scenario_state(project, self.get_user_preferences()) if project is not None else None
        history_match = re.search("\u6700\u8fd1\\s*(\\d+)\\s*\u6761", text)
        if history_match:
            command.history_limit = int(history_match.group(1))
            command.intent = UserIntent.VIEW_HISTORY
        elif command.intent == UserIntent.UNKNOWN and "\u5386\u53f2" in text:
            command.intent = UserIntent.VIEW_HISTORY
        if any(token in text for token in ("\u76f4\u63a5\u8fd0\u884c", "\u5e76\u8fd0\u884c", "\u8fd0\u884c\u4e00\u4e0b", "\u542f\u52a8\u4eff\u771f", "\u751f\u6210\u540e\u8fd0\u884c", "\u8dd1\u8d77\u6765")):
            command.should_run_simulation = True
        elif command.intent == UserIntent.RUN_SIMULATION:
            command.should_run_simulation = True
        scenario_type = self._normalize_topology(text)
        if scenario_type is not None:
            command.scenario_type = scenario_type
        directional_lanes = self._extract_directional_lane_updates(text)
        if directional_lanes.has_any():
            command.directional_lanes = directional_lanes
            fallback_topology = command.scenario_type or (base_state.scenario_type if base_state else "intersection")
            current_lane_count = base_state.lane_count if base_state else 2
            command.lane_count = directional_lanes.effective_lane_count(fallback_topology, current_lane_count)
        lane_match = re.search("([0-9\u4e00\u4e8c\u4e24\u4e09\u56db\u4e94\u516d\u4e03\u516b\u4e5d\u5341]+)\\s*\u8f66\u9053", text)
        if lane_match and command.directional_lanes is None:
            command.lane_count = self._parse_chinese_number(lane_match.group(1))
        length_match = re.search("(?:\u957f\u5ea6|\u8def\u6bb5\u957f\u5ea6|\u9053\u8def\u957f\u5ea6)(?:\u4e3a|=|\u6539\u6210|\u6539\u4e3a|\u8bbe\u4e3a|\u8bbe\u7f6e\u4e3a|\u8c03\u6574\u4e3a)?\\s*(\\d+(?:\\.\\d+)?)\\s*(?:\u7c73|m)?", text, re.IGNORECASE)
        if length_match:
            command.road_length = float(length_match.group(1))
        seconds_match = re.search("(\\d+(?:\\.\\d+)?)\\s*\u79d2", text)
        minutes_match = re.search("(\\d+(?:\\.\\d+)?)\\s*(?:\u5206\u949f|\u5206)", text)
        hours_match = re.search("(\\d+(?:\\.\\d+)?)\\s*(?:\u5c0f\u65f6|h)", text, re.IGNORECASE)
        if seconds_match:
            command.duration_seconds = int(float(seconds_match.group(1)))
        elif minutes_match:
            command.duration_seconds = int(float(minutes_match.group(1)) * 60)
        elif hours_match:
            command.duration_seconds = int(float(hours_match.group(1)) * 3600)
        step_match = re.search("\u6b65\u957f(?:\u4e3a|=|\u6539\u6210|\u6539\u4e3a|\u8bbe\u4e3a|\u8bbe\u7f6e\u4e3a|\u8c03\u6574\u4e3a)?\\s*(\\d+(?:\\.\\d+)?)", text)
        if step_match:
            command.step_length = float(step_match.group(1))
        seed_match = re.search("(?:\u79cd\u5b50|seed)(?:\u4e3a|=|\u8bbe\u4e3a)?\\s*(\\d+)", text, re.IGNORECASE)
        if seed_match:
            command.seed = int(seed_match.group(1))
        speed_match = re.search("(?:\u9650\u901f|\u901f\u5ea6)(?:\u4e3a|=|\u6539\u6210|\u6539\u4e3a|\u8bbe\u4e3a|\u8bbe\u7f6e\u4e3a|\u8c03\u6574\u4e3a)?\\s*(\\d+(?:\\.\\d+)?)\\s*(km/h|kmh|\u516c\u91cc/\u5c0f\u65f6|m/s)?", text, re.IGNORECASE)
        if speed_match:
            speed_value = float(speed_match.group(1))
            unit = (speed_match.group(2) or "").lower()
            if unit in {"km/h", "kmh", "\u516c\u91cc/\u5c0f\u65f6"} or speed_value > 40:
                speed_value = speed_value / 3.6
            command.speed_limit = round(speed_value, 2)
        explicit_flow_match = re.search("\u6d41\u91cf(?:\u4e3a|=|\u6539\u6210|\u6539\u4e3a|\u8bbe\u4e3a|\u8bbe\u7f6e\u4e3a|\u8c03\u6574\u4e3a|\u5230)?\\s*(\\d{2,5})\\s*(?:\u8f86/\u5c0f\u65f6|veh/h|vph)?", text, re.IGNORECASE)
        if explicit_flow_match:
            command.flow_rate = int(explicit_flow_match.group(1))
            command.flow_level = self._infer_flow_level(command.flow_rate)
        increase_match = re.search("\u6d41\u91cf(?:\u63d0\u9ad8|\u589e\u52a0)\\s*(\\d+(?:\\.\\d+)?)%", text)
        decrease_match = re.search("\u6d41\u91cf(?:\u964d\u4f4e|\u51cf\u5c11)\\s*(\\d+(?:\\.\\d+)?)%", text)
        if command.flow_rate is None:
            if increase_match:
                command.flow_multiplier = 1.0 + float(increase_match.group(1)) / 100.0
            elif decrease_match:
                command.flow_multiplier = max(0.0, 1.0 - float(decrease_match.group(1)) / 100.0)
        if command.flow_level is None:
            if any(token in text for token in ("\u9ad8\u6d41\u91cf", "\u9ad8\u5cf0", "\u62e5\u5835")):
                command.flow_level = "high"
            elif any(token in text for token in ("\u4f4e\u6d41\u91cf", "\u7a00\u758f", "\u6d41\u91cf\u5c0f")):
                command.flow_level = "low"
            elif any(token in text for token in ("\u4e2d\u6d41\u91cf", "\u4e2d\u7b49\u6d41\u91cf", "\u666e\u901a\u6d41\u91cf")):
                command.flow_level = "medium"
        if any(token in text for token in ("\u53d6\u6d88\u504f\u5411", "\u6e05\u7a7a\u504f\u5411", "\u53bb\u6389\u504f\u5411")):
            command.reset_traffic_bias = True
        elif "\u5357\u5317" in text:
            command.traffic_bias = "north_south"
        elif "\u4e1c\u897f" in text:
            command.traffic_bias = "east_west"
        if any(token in text for token in ("\u53d6\u6d88\u968f\u673a\u79cd\u5b50", "\u6e05\u7a7a\u968f\u673a\u79cd\u5b50", "\u6e05\u7a7aseed", "\u53d6\u6d88seed", "\u4e0d\u8981\u79cd\u5b50")):
            command.reset_seed = True
        if any(token in text for token in ("\u6062\u590d\u9ed8\u8ba4\u6d41\u91cf", "\u6d41\u91cf\u6062\u590d\u9ed8\u8ba4")):
            command.reset_flow_to_default = True
        if any(token in text for token in ("\u6062\u590d\u9ed8\u8ba4\u65f6\u957f", "\u65f6\u957f\u6062\u590d\u9ed8\u8ba4")):
            command.reset_duration_to_default = True
        if any(token in text for token in ("\u6062\u590d\u9ed8\u8ba4\u6b65\u957f", "\u6b65\u957f\u6062\u590d\u9ed8\u8ba4")):
            command.reset_step_length_to_default = True
        preference_updates: dict[str, Any] = {}
        if any(token in text for token in ("\u9ed8\u8ba4\u573a\u666f", "\u504f\u597d\u573a\u666f")) and command.scenario_type and "\u6062\u590d\u9ed8\u8ba4" not in text:
            preference_updates["default_scenario_type"] = command.scenario_type
        if any(token in text for token in ("\u9ed8\u8ba4\u6d41\u91cf", "\u504f\u597d\u6d41\u91cf")) and command.flow_level and "\u6062\u590d\u9ed8\u8ba4" not in text:
            preference_updates["default_flow_level"] = command.flow_level
        if any(token in text for token in ("\u9ed8\u8ba4\u65f6\u957f", "\u9ed8\u8ba4\u4eff\u771f\u65f6\u957f")) and command.duration_seconds and "\u6062\u590d\u9ed8\u8ba4" not in text:
            preference_updates["default_duration"] = command.duration_seconds
        if preference_updates:
            command.intent = UserIntent.UPDATE_PREFERENCES
            command.preference_updates = preference_updates
        return command

    @staticmethod
    def _parse_chinese_number(raw: str) -> int:
        if raw.isdigit():
            return int(raw)
        mapping = {"\u96f6": 0, "\u4e00": 1, "\u4e8c": 2, "\u4e24": 2, "\u4e09": 3, "\u56db": 4, "\u4e94": 5, "\u516d": 6, "\u4e03": 7, "\u516b": 8, "\u4e5d": 9, "\u5341": 10}
        if raw == "\u5341":
            return 10
        if raw.startswith("\u5341"):
            return 10 + mapping.get(raw[1], 0)
        if raw.endswith("\u5341"):
            return mapping.get(raw[0], 0) * 10
        if "\u5341" in raw:
            left, right = raw.split("\u5341", 1)
            return mapping.get(left, 0) * 10 + mapping.get(right, 0)
        return mapping.get(raw, 2)

    def _should_try_model_fallback(self, command: ParsedCommand) -> bool:
        if command.intent == UserIntent.UNKNOWN:
            return True
        if command.intent == UserIntent.EDIT_SCENARIO and not self._has_edit_payload(command):
            return True
        if command.intent == UserIntent.UPDATE_PREFERENCES and not command.preference_updates:
            return True
        return False

    @staticmethod
    def _has_edit_payload(command: ParsedCommand) -> bool:
        return any(value is not None for value in (command.scenario_type, command.lane_count, command.lane_delta, command.road_length, command.speed_limit, command.duration_seconds, command.step_length, command.flow_level, command.flow_rate, command.flow_multiplier, command.traffic_bias, command.seed)) or (command.directional_lanes is not None and command.directional_lanes.has_any()) or any((command.reset_traffic_bias, command.reset_seed, command.reset_flow_to_default, command.reset_duration_to_default, command.reset_step_length_to_default))

    def _extract_json_object(self, text: str) -> dict | None:
        if not text:
            return None
        stripped = text.strip()
        try:
            parsed = json.loads(stripped)
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            pass
        match = re.search(r"\{.*\}", stripped, re.DOTALL)
        if not match:
            return None
        try:
            parsed = json.loads(match.group(0))
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None

    def _fallback_reply(self, command: ParsedCommand, project: ProjectContext | None) -> str:
        if command.intent == UserIntent.RUN_SIMULATION:
            if project is None:
                return "\u5f53\u524d\u6ca1\u6709\u9879\u76ee\u4e0a\u4e0b\u6587\u3002\u8bf7\u5148\u751f\u6210\u573a\u666f\uff0c\u6216\u5148\u65b0\u5efa\u9879\u76ee\u540e\u518d\u8fd0\u884c\u3002"
            return f"\u5df2\u6536\u5230\u8fd0\u884c\u8bf7\u6c42\uff0c\u5f53\u524d\u9879\u76ee\u662f {project.meta.name}\u3002"
        if command.intent == UserIntent.SUMMARIZE_PROJECT:
            if project is None:
                return "\u5f53\u524d\u6ca1\u6709\u9879\u76ee\u4e0a\u4e0b\u6587\u3002\u8bf7\u5148\u751f\u6210\u573a\u666f\u6216\u521b\u5efa\u9879\u76ee\u3002"
            return self._format_project_summary(project, self._derive_scenario_state(project, self.get_user_preferences()))
        if command.intent == UserIntent.VIEW_HISTORY:
            return "\u4f60\u53ef\u4ee5\u76f4\u63a5\u8bf4\u201c\u770b\u770b\u6700\u8fd1 5 \u6761\u5386\u53f2\u201d\u6216\u201c\u67e5\u770b\u64cd\u4f5c\u5386\u53f2\u201d\uff0c\u6211\u4f1a\u5e2e\u4f60\u6574\u7406\u6700\u8fd1\u7684\u9879\u76ee\u53d8\u66f4\u3002"
        if command.intent == UserIntent.UPDATE_PREFERENCES:
            return "\u4f60\u53ef\u4ee5\u76f4\u63a5\u8bf4\u201c\u4ee5\u540e\u9ed8\u8ba4\u573a\u666f\u7528\u5341\u5b57\u8def\u53e3\u201d\u6216\u201c\u9ed8\u8ba4\u65f6\u957f\u6539\u6210 1200 \u79d2\u201d\uff0c\u6211\u4f1a\u5e2e\u4f60\u66f4\u65b0\u504f\u597d\u3002"
        return f"\u6211\u662f {ASSISTANT_NAME}\uff0c\u4e3b\u8981\u8d1f\u8d23 TrafficAgent \u91cc\u7684\u573a\u666f\u751f\u6210\u3001\u53c2\u6570\u8c03\u6574\u3001\u9879\u76ee\u6458\u8981\u3001\u5386\u53f2\u67e5\u8be2\u3001\u56fe\u7247\u8bc6\u522b\u548c\u4eff\u771f\u8fd0\u884c\u3002"

    def _fallback_tool_reply(self, user_text: str, project: ProjectContext | None, tool_summaries: list[ToolExecutionSummary], issues: list[str]) -> str:
        lines = [f"\u6211\u7406\u89e3\u4f60\u7684\u610f\u601d\u662f\uff1a{user_text}", "\u672c\u8f6e\u6211\u5df2\u7ecf\u5b8c\u6210\u8fd9\u4e9b\u52a8\u4f5c\uff1a"]
        lines.extend(f"- {item.summary}" for item in tool_summaries if item.summary)
        if project is not None:
            lines.extend(["", "\u5f53\u524d\u9879\u76ee\u72b6\u6001\uff1a", self._format_project_summary(project, self._derive_scenario_state(project, self.get_user_preferences()))])
        if issues:
            lines.append("")
            lines.append("\u9700\u8981\u6ce8\u610f\uff1a")
            lines.extend(f"- {item}" for item in issues)
        return chr(10).join(lines)

    @staticmethod
    def _format_model_error(message: str) -> str:
        compact = " ".join(message.split())
        if len(compact) <= 240:
            return compact
        return f"{compact[:237]}..."

    def _infer_flow_level(self, flow_rate: int) -> str:
        if flow_rate < 450:
            return "low"
        if flow_rate < 900:
            return "medium"
        if flow_rate < 1500:
            return "high"
        return "very_high"

    @staticmethod
    def _infer_traffic_bias(project: ProjectContext) -> str | None:
        if not project.routes or not project.routes.flows:
            return None
        ns_total = sum(flow.vehs_per_hour for flow in project.routes.flows if flow.from_edge in {"north_in", "south_in"})
        ew_total = sum(flow.vehs_per_hour for flow in project.routes.flows if flow.from_edge in {"east_in", "west_in"})
        if ns_total > ew_total:
            return "north_south"
        if ew_total > ns_total:
            return "east_west"
        return None

    def _describe_flow(self, state: ProjectScenarioState) -> str:
        if state.flow_rate is not None:
            return f"{state.flow_rate} veh/h"
        return state.flow_level

    def _format_project_summary(self, project: ProjectContext, state: ProjectScenarioState) -> str:
        bias_map = {"north_south": "\u5357\u5317\u5411", "east_west": "\u4e1c\u897f\u5411", None: "\u65e0"}
        seed = state.seed if state.seed is not None else "auto"
        return chr(10).join([
            f"\u5f53\u524d\u9879\u76ee\uff1a{project.meta.name}",
            f"\u573a\u666f={self._label_scenario(state.scenario_type)}",
            f"\u8f66\u9053={self._format_lane_summary(state)}",
            f"\u9053\u8def\u957f\u5ea6={int(round(state.road_length))}m\uff0c\u9650\u901f={self._format_speed_limit(state.speed_limit)}",
            f"\u6d41\u91cf={self._describe_flow(state)}\uff0c\u504f\u5411={bias_map.get(state.traffic_bias, state.traffic_bias or '')}",
            f"\u65f6\u957f={state.duration_seconds}s\uff0c\u6b65\u957f={state.step_length}\uff0cseed={seed}",
            f"\u4e0a\u4e0b\u6587\uff1anetwork={'yes' if project.network else 'no'}\uff0croutes={'yes' if project.routes else 'no'}\uff0csimulation={'yes' if project.simulation else 'no'}",
        ])

    def _build_state_change_summary(self, before: ProjectScenarioState | None, after: ProjectScenarioState) -> str:
        if before is None:
            return chr(10).join([
                f"- \u5df2\u521b\u5efa\u573a\u666f\uff1a{self._label_scenario(after.scenario_type)}",
                f"- \u8f66\u9053\uff1a{self._format_lane_summary(after)}",
                f"- \u9053\u8def\u957f\u5ea6\uff1a{int(round(after.road_length))}m",
                f"- \u9650\u901f\uff1a{self._format_speed_limit(after.speed_limit)}",
                f"- \u6d41\u91cf\uff1a{self._describe_flow(after)}",
                f"- \u4eff\u771f\u65f6\u957f\uff1a{after.duration_seconds}s",
                f"- \u4eff\u771f\u6b65\u957f\uff1a{after.step_length}",
            ])
        changes = self._collect_state_changes(before, after)
        return "- \u672a\u68c0\u6d4b\u5230\u53c2\u6570\u53d8\u5316\uff0c\u5df2\u6309\u5f53\u524d\u72b6\u6001\u91cd\u65b0\u751f\u6210 SUMO \u6587\u4ef6\u3002" if not changes else chr(10).join(f"- {item}" for item in changes)

    def _collect_state_changes(self, before: ProjectScenarioState, after: ProjectScenarioState) -> list[str]:
        labels = {"scenario_type": "\u573a\u666f\u7c7b\u578b", "lane_count": "\u7edf\u4e00\u8f66\u9053\u6570", "directional_lanes": "\u65b9\u5411\u8f66\u9053", "road_length": "\u9053\u8def\u957f\u5ea6", "speed_limit": "\u9650\u901f", "flow_level": "\u6d41\u91cf\u7b49\u7ea7", "flow_rate": "\u6d41\u91cf", "traffic_bias": "\u4ea4\u901a\u504f\u5411", "duration_seconds": "\u4eff\u771f\u65f6\u957f", "step_length": "\u4eff\u771f\u6b65\u957f", "seed": "\u968f\u673a\u79cd\u5b50"}
        before_dict = before.model_dump(mode="json")
        after_dict = after.model_dump(mode="json")
        changes: list[str] = []
        for field, label in labels.items():
            if before_dict.get(field) != after_dict.get(field):
                changes.append(f"{label}: {self._format_state_value(field, before_dict.get(field))} -> {self._format_state_value(field, after_dict.get(field))}")
        return changes

    def _format_state_value(self, field: str, value: Any) -> str:
        if field == "scenario_type":
            return self._label_scenario(value)
        if field == "directional_lanes":
            lanes = self._coerce_directional_lanes(value)
            return "\u65e0" if not lanes.has_any() else "\uff1b".join(f"{DirectionalLaneConfig.edge_label(edge_id)} {getattr(lanes, edge_id)}" for edge_id in DirectionalLaneConfig.EDGE_ORDER if getattr(lanes, edge_id) is not None)
        if field == "road_length":
            return f"{int(round(float(value)))}m"
        if field == "speed_limit":
            return self._format_speed_limit(float(value))
        if field == "flow_rate":
            return "auto" if value is None else f"{int(value)} veh/h"
        if field == "traffic_bias":
            return {"north_south": "\u5357\u5317\u5411", "east_west": "\u4e1c\u897f\u5411"}.get(value, value or "\u65e0")
        if field == "duration_seconds":
            return f"{int(value)}s"
        if field == "seed":
            return "auto" if value is None else str(value)
        return str(value)

    def _label_scenario(self, scenario_type: str | None) -> str:
        return {"intersection": "\u5341\u5b57\u8def\u53e3", "t_junction": "T \u5b57\u8def\u53e3", "corridor": "\u76f4\u7ebf\u8def\u6bb5"}.get(scenario_type, scenario_type or "\u672a\u8bbe\u7f6e")

    @staticmethod
    def _format_speed_limit(speed_limit: float) -> str:
        return f"{speed_limit * 3.6:.1f} km/h"

    def _record_operation(
        self,
        command: ParsedCommand,
        user_message: str,
        previous_project: ProjectContext | None,
        result: AgentExecutionResult,
    ) -> ProjectOperationRecord | None:
        if command.intent not in self.TRACKED_INTENTS:
            return None

        project = result.updated_project or previous_project
        project_name = project.meta.name if project is not None else None
        project_dir = str(project.meta.project_dir) if project is not None else None

        summary = result.operation_summary or self._fallback_history_summary(command, result)
        record = ProjectOperationRecord(
            created_at=datetime.now(),
            project_name=project_name,
            project_dir=project_dir,
            intent=command.intent.value,
            user_message=user_message,
            change_summary=summary,
            before_state=result.before_state,
            after_state=result.after_state,
            generated_files=result.generated_files,
            issues=result.issues,
        )
        return self.history_store.add_record(record)

    def _fallback_history_summary(self, command: ParsedCommand, result: AgentExecutionResult) -> str:
        if command.intent == UserIntent.RUN_SIMULATION:
            return "\u6536\u5230\u8fd0\u884c\u8bf7\u6c42\u3002"
        if command.intent == UserIntent.SUMMARIZE_PROJECT:
            return "\u67e5\u770b\u5f53\u524d\u9879\u76ee\u6458\u8981\u3002"
        if command.intent == UserIntent.UPDATE_PREFERENCES:
            return "\u66f4\u65b0\u7528\u6237\u504f\u597d\u3002"
        return result.reply_text.splitlines()[0] if result.reply_text else command.intent.value

    def analyze_uploaded_image(
        self,
        image_path: str | Path,
        project: ProjectContext | None,
        progress_callback: Callable[[AssistantProgress], None] | None = None,
    ) -> ImageAnalysisResult:
        image_file = Path(image_path)
        self.memory.append_user_message(f"[image] {image_file.name}")
        if not image_file.exists() or not image_file.is_file():
            result = ImageAnalysisResult(
                status=ImageAnalysisStatus.INVALID_RESULT,
                reply_text="\u672a\u627e\u5230\u8981\u89e3\u6790\u7684\u56fe\u7247\u6587\u4ef6\u3002",
                issues=["image_not_found"],
                allow_reupload=True,
            )
            self.memory.append_agent_message(result.reply_text)
            return result
        if image_file.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
            result = ImageAnalysisResult(
                status=ImageAnalysisStatus.INVALID_RESULT,
                reply_text="\u5f53\u524d\u53ea\u652f\u6301 png/jpg/jpeg/webp \u56fe\u7247\u3002",
                issues=["unsupported_image_format"],
                allow_reupload=True,
            )
            self.memory.append_agent_message(result.reply_text)
            return result
        if not self.get_model_config().supports_vision:
            result = ImageAnalysisResult(
                status=ImageAnalysisStatus.INVALID_RESULT,
                reply_text="\u5f53\u524d\u6a21\u578b\u672a\u542f\u7528\u56fe\u7247\u8bc6\u522b\u80fd\u529b\uff0c\u8bf7\u5728\u8bbe\u7f6e\u91cc\u66f4\u6362\u6216\u542f\u7528\u89c6\u89c9\u6a21\u578b\u3002",
                issues=["vision_model_required"],
                allow_reupload=True,
            )
            self.memory.append_agent_message(result.reply_text)
            return result

        preferences = self.get_user_preferences()
        project_summary = self.preference_context_builder.build_project_summary(preferences, project)
        self._emit_progress(progress_callback, "\u8bfb\u53d6\u56fe\u7247\u4e2d", f"{ASSISTANT_NAME} \u6b63\u5728\u8bfb\u53d6\u56fe\u7247...")
        self._emit_progress(progress_callback, "\u8bc6\u522b\u8def\u53e3\u4e2d", f"{ASSISTANT_NAME} \u6b63\u5728\u8bc6\u522b\u8def\u53e3...")
        try:
            payload = self._analyze_image_with_model(image_file, project_summary)
            result = self._coerce_image_result(image_file, payload)
        except Exception as exc:
            result = ImageAnalysisResult(
                status=ImageAnalysisStatus.INVALID_RESULT,
                reply_text="\u8bc6\u522b\u5931\u8d25\uff0c\u8bf7\u6362\u66f4\u6e05\u6670\u7684\u4fde\u89c6\u8def\u53e3\u56fe\uff0c\u6216\u68c0\u67e5\u5f53\u524d\u6a21\u578b\u662f\u5426\u652f\u6301\u56fe\u7247\u8bc6\u522b\u3002",
                issues=[self._format_model_error(str(exc) or exc.__class__.__name__)],
                allow_reupload=True,
            )
        self._emit_progress(progress_callback, "\u6821\u9a8c\u7ed3\u679c\u4e2d", f"{ASSISTANT_NAME} \u6b63\u5728\u6821\u9a8c\u8bc6\u522b\u7ed3\u679c...")
        self.memory.append_agent_message(result.reply_text)
        return result

    def update_image_draft_from_text(
        self,
        text: str,
        draft: IntersectionImageDraft,
        project: ProjectContext | None,
        progress_callback: Callable[[AssistantProgress], None] | None = None,
    ) -> ImageAnalysisResult:
        self.memory.append_user_message(text)
        self._emit_progress(progress_callback, "\u7406\u89e3\u4e2d", f"{ASSISTANT_NAME} \u6b63\u5728\u7406\u89e3\u4f60\u5bf9\u56fe\u7247\u8349\u7a3f\u7684\u4fee\u6539...")
        preferences = self.get_user_preferences()
        project_summary = self.preference_context_builder.build_project_summary(preferences, project)
        patch = self._patch_draft_with_model(text, draft, project_summary)
        if not patch:
            patch = self._patch_draft_with_rules(text)
        if not patch:
            result = ImageAnalysisResult(
                status=ImageAnalysisStatus.DRAFT_READY,
                reply_text="\u6211\u6682\u65f6\u6ca1\u6709\u8bc6\u522b\u5230\u9700\u8981\u4fee\u6539\u7684\u56fe\u7247\u8349\u7a3f\u5b57\u6bb5\u3002\u4f60\u53ef\u4ee5\u76f4\u63a5\u8bf4\u201c\u5317\u5411\u5165\u53e3\u6539\u6210 3 \u8f66\u9053\u201d\u6216\u201c\u9650\u901f\u6539 50 km/h\u201d\u3002",
                draft=draft,
                allow_confirm=draft.can_confirm(),
                allow_customize=True,
            )
            self.memory.append_agent_message(result.reply_text)
            return result

        self._emit_progress(progress_callback, "\u6821\u9a8c\u7ed3\u679c\u4e2d", f"{ASSISTANT_NAME} \u6b63\u5728\u6821\u9a8c\u4fee\u6539\u540e\u7684\u8349\u7a3f...")
        updated_draft = self._merge_draft_patch(draft, patch)
        result = self._coerce_image_result(Path(updated_draft.source_image_path), updated_draft.model_dump(mode="json"))
        if result.status == ImageAnalysisStatus.DRAFT_READY:
            missing_fields = result.draft.missing_fields() if result.draft else []
            if missing_fields:
                result.reply_text = "\u6211\u5df2\u7ecf\u66f4\u65b0\u8fd9\u5f20\u56fe\u7684\u8def\u53e3\u8349\u7a3f\uff0c\u4f46\u8fd8\u9700\u8981\u8865\u9f50\u7f3a\u5931\u5b57\u6bb5\u540e\u624d\u80fd\u751f\u6210\u3002"
            else:
                result.reply_text = "\u6211\u5df2\u7ecf\u6309\u4f60\u7684\u8bf4\u660e\u5237\u65b0\u4e86\u8fd9\u5f20\u8def\u53e3\u8349\u7a3f\u3002\u4f60\u53ef\u4ee5\u7ee7\u7eed\u7528\u804a\u5929\u5fae\u8c03\uff0c\u6216\u76f4\u63a5\u786e\u8ba4\u751f\u6210\u3002"
            result.allow_customize = True
            result.allow_confirm = bool(result.draft and result.draft.can_confirm())
        self.memory.append_agent_message(result.reply_text)
        return result

    def materialize_image_draft(
        self,
        draft: IntersectionImageDraft,
        project: ProjectContext | None,
        progress_callback: Callable[[AssistantProgress], None] | None = None,
        should_run_simulation: bool = False,
    ) -> AgentExecutionResult:
        if not draft.can_confirm():
            missing_fields = ", ".join(draft.missing_fields()) or "draft_incomplete"
            result = AgentExecutionResult(
                reply_text=f"\u8fd9\u5f20\u56fe\u7247\u8349\u7a3f\u8fd8\u4e0d\u5b8c\u6574\uff0c\u6682\u65f6\u4e0d\u80fd\u751f\u6210 SUMO \u9879\u76ee\u3002\u7f3a\u5931\u5b57\u6bb5\uff1a{missing_fields}\u3002",
                updated_project=project,
                issues=[f"image_draft_incomplete: {missing_fields}"],
                response_mode="chat",
                assistant_name=ASSISTANT_NAME,
            )
            self.memory.append_agent_message(result.reply_text)
            return result

        self.memory.append_user_message(f"[confirm-image-draft] {draft.image_name()}")
        self._emit_progress(progress_callback, "\u751f\u6210\u9879\u76ee\u4e2d", f"{ASSISTANT_NAME} \u6b63\u5728\u6839\u636e\u56fe\u7247\u8349\u7a3f\u751f\u6210\u9879\u76ee...")
        tool_call = ToolCall(name="generate_scenario", arguments=draft.to_generate_arguments(should_run_simulation))
        tool_summaries, result = self.execute_tool_plan([tool_call], project)
        self._emit_progress(progress_callback, "\u6574\u7406\u7ed3\u679c", f"{ASSISTANT_NAME} \u6b63\u5728\u6574\u7406\u56fe\u7247\u751f\u6210\u7ed3\u679c...")
        user_text = f"\u6839\u636e\u56fe\u7247\u751f\u6210\u573a\u666f\uff1a{draft.image_name()}"
        result.reply_text = self.summarize_result(user_text, result.updated_project or project, tool_summaries, result.issues)
        history_command = ParsedCommand(
            intent=UserIntent.EDIT_SCENARIO if project is not None else UserIntent.CREATE_SCENARIO,
            scenario_type=draft.topology,
            lane_count=draft.recommended_lane_count(),
            directional_lanes=draft.directional_lanes,
            road_length=draft.road_length_m,
            speed_limit=(draft.speed_limit_kmh / 3.6) if draft.speed_limit_kmh is not None else None,
            should_run_simulation=should_run_simulation,
        )
        history_record = self._record_operation(history_command, user_text, project, result)
        if history_record is not None:
            result.history_record_id = history_record.id
            result.reply_text = chr(10).join([result.reply_text, "", f"\u5df2\u8bb0\u5f55\u5230\u64cd\u4f5c\u5386\u53f2\uff1a#{history_record.id}"])
        combined_summary = " | ".join(item.summary for item in tool_summaries if item.summary)
        if combined_summary:
            self.memory.append_tool_summary(combined_summary)
        self.memory.append_agent_message(result.reply_text)
        return result

    @staticmethod
    def is_confirm_draft_text(text: str) -> bool:
        return any(token in text for token in ("\u786e\u8ba4\u751f\u6210", "\u786e\u5b9a\u751f\u6210", "\u786e\u8ba4\u4e00\u4e0b\u751f\u6210", "\u5c31\u6309\u8fd9\u4e2a\u751f\u6210", "\u6309\u8fd9\u4e2a\u751f\u6210", "\u6309\u8fd9\u4e2a\u6765", "\u5c31\u8fd9\u6837", "\u5c31\u7528\u8fd9\u4e2a", "\u751f\u6210\u8fd9\u4e2a", "\u751f\u6210\u5427", "\u53ef\u4ee5\u751f\u6210\u4e86", "\u76f4\u63a5\u751f\u6210", "\u5f00\u59cb\u751f\u6210"))

    @staticmethod
    def is_cancel_draft_text(text: str) -> bool:
        return any(token in text for token in ("\u53d6\u6d88\u8349\u7a3f", "\u53d6\u6d88\u8fd9\u5f20\u56fe", "\u4e0d\u8981\u8fd9\u5f20\u56fe", "\u53d6\u6d88\u8bc6\u522b", "\u7b97\u4e86"))

    @classmethod
    def should_route_to_image_draft(cls, text: str) -> bool:
        lowered = text.lower()
        tokens = (
            "\u5317\u5411",
            "\u5357\u5411",
            "\u4e1c\u5411",
            "\u897f\u5411",
            "\u5165\u53e3",
            "\u51fa\u53e3",
            "\u8f66\u9053",
            "\u9650\u901f",
            "\u901f\u5ea6",
            "\u957f\u5ea6",
            "\u6539\u6210",
            "\u6539\u4e3a",
            "\u8bbe\u4e3a",
            "\u8c03\u6574",
            "\u5341\u5b57",
            "t\u5b57",
            "T\u5b57",
            "\u4e01\u5b57",
            "\u76f4\u7ebf",
            "\u8def\u6bb5",
        )
        return any(token in text for token in tokens) or "lane" in lowered or "speed" in lowered

    def _extract_directional_lane_updates(self, text: str) -> DirectionalLaneConfig:
        config_data: dict[str, int] = {}
        edge_patterns = {
            "north_in": ("\u5317\u5411\u5165\u53e3", "\u5317\u5165\u53e3", "north in", "north_in"),
            "north_out": ("\u5317\u5411\u51fa\u53e3", "\u5317\u51fa\u53e3", "north out", "north_out"),
            "south_in": ("\u5357\u5411\u5165\u53e3", "\u5357\u5165\u53e3", "south in", "south_in"),
            "south_out": ("\u5357\u5411\u51fa\u53e3", "\u5357\u51fa\u53e3", "south out", "south_out"),
            "west_in": ("\u897f\u5411\u5165\u53e3", "\u897f\u5165\u53e3", "west in", "west_in"),
            "west_out": ("\u897f\u5411\u51fa\u53e3", "\u897f\u51fa\u53e3", "west out", "west_out"),
            "east_in": ("\u4e1c\u5411\u5165\u53e3", "\u4e1c\u5165\u53e3", "east in", "east_in"),
            "east_out": ("\u4e1c\u5411\u51fa\u53e3", "\u4e1c\u51fa\u53e3", "east out", "east_out"),
        }
        for edge_id, patterns in edge_patterns.items():
            for pattern in patterns:
                match = re.search(rf"(?:{re.escape(pattern)}).{{0,12}}?([0-9\u4e00\u4e8c\u4e24\u4e09\u56db\u4e94\u516d\u4e03\u516b\u4e5d\u5341]+)\s*\u8f66\u9053", text, re.IGNORECASE)
                if match:
                    config_data[edge_id] = self._parse_chinese_number(match.group(1))
                    break
        return DirectionalLaneConfig(**config_data)

    def _patch_draft_with_rules(self, text: str) -> dict[str, Any] | None:
        patch: dict[str, Any] = {}
        topology = self._normalize_topology(text)
        if topology is not None:
            patch["topology"] = topology
        lanes = self._extract_directional_lane_updates(text)
        if lanes.has_any():
            patch["directional_lanes"] = lanes.model_dump(exclude_none=True)
        length_match = re.search(r"(?:??|????|????)(?:?|=|??|??|??|???|???)?\s*(\d+(?:\.\d+)?)\s*(?:?|m)?", text, re.IGNORECASE)
        if length_match:
            patch["road_length_m"] = float(length_match.group(1))
        speed_match = re.search(r"(?:??|??)(?:?|=|??|??|??|???|???)?\s*(\d+(?:\.\d+)?)\s*(km/h|kmh|??/??|m/s)?", text, re.IGNORECASE)
        if speed_match:
            speed_value = float(speed_match.group(1))
            unit = (speed_match.group(2) or "").lower()
            if unit == "m/s":
                speed_value *= 3.6
            patch["speed_limit_kmh"] = round(speed_value, 2)
        return patch or None

    def _coerce_directional_lanes(self, value: Any) -> DirectionalLaneConfig:
        if isinstance(value, DirectionalLaneConfig):
            return value
        if not isinstance(value, dict):
            return DirectionalLaneConfig()
        data: dict[str, int] = {}
        for edge_id in DirectionalLaneConfig.EDGE_ORDER:
            raw = value.get(edge_id)
            if raw is None:
                continue
            try:
                lane_value = int(raw)
            except (TypeError, ValueError):
                continue
            if lane_value >= 1:
                data[edge_id] = lane_value
        return DirectionalLaneConfig(**data)

    def _normalize_topology(self, value: Any) -> str | None:
        if value is None:
            return None
        lowered = str(value).strip().lower()
        mapping = {
            "intersection": "intersection",
            "cross": "intersection",
            "crossroad": "intersection",
            "??": "intersection",
            "????": "intersection",
            "t": "t_junction",
            "t_junction": "t_junction",
            "t-junction": "t_junction",
            "t?": "t_junction",
            "??": "t_junction",
            "????": "t_junction",
            "corridor": "corridor",
            "straight": "corridor",
            "road": "corridor",
            "??": "corridor",
            "??": "corridor",
            "??": "corridor",
        }
        return mapping.get(lowered)

    @staticmethod
    def _coerce_float(value: Any) -> float | None:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _format_lane_summary(self, state: ProjectScenarioState) -> str:
        if state.directional_lanes and state.directional_lanes.has_any():
            merged = state.directional_lanes.merged_with_fallback(state.scenario_type, state.lane_count)
            parts = [f"{DirectionalLaneConfig.edge_label(edge_id)} {getattr(merged, edge_id)}" for edge_id in DirectionalLaneConfig.valid_edge_ids(state.scenario_type)]
            return "\uff1b".join(parts)
        return f"\u7edf\u4e00\u8f66\u9053\u6570 {state.lane_count}"

    def _analyze_image_with_model(self, image_file: Path, project_summary: str | None) -> dict[str, Any]:
        client = self.model_client_factory.create(self.get_model_config())
        data_uri = self._image_to_data_uri(image_file)
        messages = [
            ChatMessage(role="system", content=build_image_analysis_system_prompt(self.get_user_preferences())),
            ChatMessage(
                role="user",
                content=[
                    MessageContentPart.text_part(build_image_analysis_user_prompt(project_summary)),
                    MessageContentPart.image_part(data_uri),
                ],
            ),
        ]
        response = client.chat(messages)
        payload = self._extract_json_object(response.text)
        if payload is None:
            raise ValueError("???????????? JSON ???")
        return payload

    def _patch_draft_with_model(self, text: str, draft: IntersectionImageDraft, project_summary: str | None) -> dict[str, Any] | None:
        try:
            client = self.model_client_factory.create(self.get_model_config())
            current_json = json.dumps(draft.model_dump(mode="json"), ensure_ascii=False)
            messages = [
                ChatMessage(role="system", content=build_image_patch_system_prompt(self.get_user_preferences())),
                ChatMessage(role="system", content=f"????????{project_summary or '??????????'}"),
                ChatMessage(role="user", content=build_image_patch_user_prompt(text, current_json)),
            ]
            response = client.chat(messages)
            return self._extract_json_object(response.text)
        except Exception:
            return None

    def _coerce_image_result(self, image_file: Path, payload: dict[str, Any]) -> ImageAnalysisResult:
        if not isinstance(payload, dict):
            return ImageAnalysisResult(status=ImageAnalysisStatus.INVALID_RESULT, reply_text="\u8bc6\u522b\u5931\u8d25\uff0c\u8bf7\u6362\u66f4\u6e05\u6670\u7684\u4fde\u89c6\u8def\u53e3\u56fe\u3002", issues=["invalid_image_payload"], allow_reupload=True)
        draft = IntersectionImageDraft(source_image_path=str(image_file), topology=self._normalize_topology(payload.get("topology")), is_intersection=bool(payload.get("is_intersection")), is_supported_for_generation=bool(payload.get("is_supported_for_generation")), directional_lanes=self._coerce_directional_lanes(payload.get("directional_lanes")), road_length_m=self._coerce_float(payload.get("road_length_m")), speed_limit_kmh=self._coerce_float(payload.get("speed_limit_kmh")), confidence=self._coerce_float(payload.get("confidence")), reason=str(payload.get("reason") or "").strip())
        if not draft.is_intersection:
            reason = draft.reason or "\u8fd9\u5f20\u56fe\u7247\u4e0d\u50cf\u53ef\u7528\u4e8e\u751f\u6210 SUMO \u8def\u53e3\u7684\u4fde\u89c6\u56fe\u3002"
            return ImageAnalysisResult(status=ImageAnalysisStatus.NOT_INTERSECTION, reply_text=reason, issues=["not_intersection"], allow_reupload=True)
        if draft.topology not in SUPPORTED_TOPOLOGIES or not draft.is_supported_for_generation:
            reason = draft.reason or "\u6211\u8bc6\u522b\u5230\u8fd9\u662f\u4e00\u5f20\u8def\u53e3\u56fe\uff0c\u4f46\u5f53\u524d\u53ea\u652f\u6301\u5341\u5b57\u8def\u53e3\u3001T \u5b57\u8def\u53e3\u548c\u76f4\u7ebf\u8def\u6bb5\u3002"
            return ImageAnalysisResult(status=ImageAnalysisStatus.UNSUPPORTED_TOPOLOGY, reply_text=reason, draft=draft, issues=["unsupported_topology"], allow_reupload=True)
        missing_fields = draft.missing_fields()
        if missing_fields:
            labels = [DirectionalLaneConfig.edge_label(item) if item in DirectionalLaneConfig.EDGE_ORDER else item for item in missing_fields]
            reply = f"\u6211\u5df2\u7ecf\u8bc6\u522b\u51fa\u8fd9\u5f20\u56fe\u7684\u8def\u53e3\u8349\u7a3f\uff0c\u4f46\u8fd8\u7f3a\u5c11\u8fd9\u4e9b\u5b57\u6bb5\uff1a{', '.join(labels)}\u3002\u4f60\u53ef\u4ee5\u7ee7\u7eed\u4fee\u6539\uff0c\u6216\u70b9\u201c\u81ea\u5b9a\u4e49\u201d\u8865\u9f50\u3002"
            return ImageAnalysisResult(status=ImageAnalysisStatus.DRAFT_READY, reply_text=reply, draft=draft, allow_customize=True, allow_reupload=True)
        return ImageAnalysisResult(status=ImageAnalysisStatus.DRAFT_READY, reply_text="\u6211\u5df2\u7ecf\u8bc6\u522b\u51fa\u8fd9\u5f20\u56fe\u7684\u8def\u53e3\u8349\u7a3f\u3002\u4f60\u53ef\u4ee5\u786e\u8ba4\u751f\u6210\uff0c\u6216\u7ee7\u7eed\u5fae\u8c03\u3002", draft=draft, allow_confirm=True, allow_customize=True, allow_reupload=True)

    def _merge_draft_patch(self, draft: IntersectionImageDraft, patch: dict[str, Any]) -> IntersectionImageDraft:
        data = draft.model_dump(mode="json")
        if patch.get("topology") is not None:
            data["topology"] = self._normalize_topology(patch.get("topology"))
        if patch.get("road_length_m") is not None:
            data["road_length_m"] = self._coerce_float(patch.get("road_length_m"))
        if patch.get("speed_limit_kmh") is not None:
            data["speed_limit_kmh"] = self._coerce_float(patch.get("speed_limit_kmh"))
        if patch.get("directional_lanes") is not None:
            current = self._coerce_directional_lanes(data.get("directional_lanes"))
            incoming = self._coerce_directional_lanes(patch.get("directional_lanes"))
            merged = current.model_dump(exclude_none=True)
            merged.update(incoming.model_dump(exclude_none=True))
            data["directional_lanes"] = merged
        return IntersectionImageDraft.model_validate(data)

    @staticmethod
    def _image_to_data_uri(image_file: Path) -> str:
        mime_type, _ = mimetypes.guess_type(str(image_file))
        mime_type = mime_type or "image/png"
        encoded = base64.b64encode(image_file.read_bytes()).decode("ascii")
        return f"data:{mime_type};base64,{encoded}"
