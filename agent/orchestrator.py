from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel, Field

from agent.intents import UserIntent
from agent.memory import PreferenceContextBuilder, SessionMemory
from agent.prompts import (
    ASSISTANT_NAME,
    build_assistant_system_prompt,
    build_capability_reply,
    build_context_system_prompt,
    build_how_to_reply,
    build_intro_reply,
    build_result_system_prompt,
    build_result_user_prompt,
)
from agent.tool_registry import ToolRegistry
from model_providers.base import ChatMessage, ToolCall
from sumo_domain.preferences import ModelConfig, UserPreferences
from sumo_domain.project_spec import (
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

        self._emit_progress(progress_callback, "理解中", f"{ASSISTANT_NAME} 正在理解你的需求...")
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

        self._emit_progress(progress_callback, "规划中", f"{ASSISTANT_NAME} 正在规划回复和工具...")
        decision = self._decide_response(text, project, context_parts)
        if decision.mode == "chat":
            fallback_command = self._parse_command(text, project)
            reply_text = decision.reply_text.strip() or self._fallback_reply(fallback_command, project)
            result = AgentExecutionResult(
                reply_text=reply_text,
                updated_project=project,
                issues=list(decision.issues),
                response_mode="chat",
                assistant_name=ASSISTANT_NAME,
            )
            self.memory.append_agent_message(result.reply_text)
            return result

        self._emit_progress(progress_callback, "执行中", f"{ASSISTANT_NAME} 正在执行工具...")
        tool_summaries, result = self.execute_tool_plan(decision.tool_calls, project)
        for issue in decision.issues:
            if issue not in result.issues:
                result.issues.append(issue)

        self._emit_progress(progress_callback, "整理结果", f"{ASSISTANT_NAME} 正在整理结果...")
        result.reply_text = self.summarize_result(text, result.updated_project or project, tool_summaries, result.issues)
        history_command = self._build_history_command(text, project, decision.tool_calls)
        history_record = self._record_operation(history_command, text, project, result)
        if history_record is not None:
            result.history_record_id = history_record.id
            result.reply_text = f"{result.reply_text}\n\n已记录到操作历史：#{history_record.id}"

        combined_summary = " | ".join(item.summary for item in tool_summaries if item.summary)
        if combined_summary:
            self.memory.append_tool_summary(combined_summary)
        self.memory.append_agent_message(result.reply_text)
        return result

    def detect_intent(self, text: str) -> UserIntent:
        lowered = text.lower()
        has_edit = any(token in text for token in ("改成", "修改", "调整", "提高", "增加", "降低", "减少", "设为", "取消", "清空", "恢复默认", "去掉"))
        has_scenario = any(token in text for token in ("生成", "创建", "新建", "十字", "T字", "t字", "丁字", "路口", "路段"))
        has_param = any(token in text for token in ("流量", "步长", "时长", "车道", "限速", "速度", "seed", "种子", "长度", "偏向", "南北", "东西"))
        has_run = any(token in text for token in ("运行", "启动", "跑", "开始仿真")) or "run" in lowered
        has_summary = any(token in text for token in ("当前项目", "项目情况", "当前场景", "场景摘要", "总结当前", "现在是什么场景", "看下当前"))
        has_history = any(token in text for token in ("操作历史", "最近变更", "查看历史", "历史记录", "最近操作", "追溯记录"))
        has_pref_words = any(token in text for token in ("偏好", "默认场景", "默认流量", "默认时长", "习惯"))

        if has_history:
            return UserIntent.VIEW_HISTORY
        if has_summary and not (has_edit or has_run or has_scenario):
            return UserIntent.SUMMARIZE_PROJECT
        if has_pref_words and not has_edit:
            return UserIntent.UPDATE_PREFERENCES
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
        project_summary = self.preference_context_builder.build_project_summary(preferences, project)
        recent_dialogue = self.memory.recent_dialogue_text()
        last_tool_summary = self.memory.last_tool_summary()
        return {
            "project_summary": project_summary,
            "recent_dialogue": recent_dialogue,
            "last_tool_summary": last_tool_summary,
        }

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
            issues.append(f"模型规划已回退到本地规则：{self._last_model_error}")
        if tool_calls:
            return AssistantDecision(mode="tool", tool_calls=tool_calls, issues=issues)
        return AssistantDecision(mode="chat", reply_text=self._fallback_reply(command, project), issues=issues)

    def _decide_with_model(
        self,
        text: str,
        context_parts: dict[str, str | None],
    ) -> AssistantDecision | None:
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
                issues.append(f"已忽略未知工具：{tool_call.name}")
                continue
            arguments = tool_call.arguments if isinstance(tool_call.arguments, dict) else {}
            normalized_calls.append(
                ToolCall(name=tool_call.name, arguments=self._normalize_tool_arguments(tool_call.name, arguments))
            )
        return normalized_calls, issues

    def _normalize_tool_arguments(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(arguments)
        bool_keys = {
            "should_run_simulation",
            "reset_traffic_bias",
            "reset_seed",
            "reset_flow_to_default",
            "reset_duration_to_default",
            "reset_step_length_to_default",
        }
        for key in bool_keys:
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
            if tool_call.name == "generate_scenario":
                intent = UserIntent.EDIT_SCENARIO if project is not None else UserIntent.CREATE_SCENARIO
                return ParsedCommand(intent=intent, should_run_simulation=bool(tool_call.arguments.get("should_run_simulation")))
            if tool_call.name == "update_preferences":
                return ParsedCommand(intent=UserIntent.UPDATE_PREFERENCES)
            if tool_call.name == "summarize_project":
                return ParsedCommand(intent=UserIntent.SUMMARIZE_PROJECT)
            if tool_call.name == "show_history":
                return ParsedCommand(intent=UserIntent.VIEW_HISTORY, history_limit=int(tool_call.arguments.get("limit", 5)))
            if tool_call.name == "request_run":
                return ParsedCommand(intent=UserIntent.RUN_SIMULATION, should_run_simulation=True)
        return command

    def _plan_tools_with_rules(self, command: ParsedCommand) -> list[ToolCall]:
        if command.intent in {UserIntent.CREATE_SCENARIO, UserIntent.EDIT_SCENARIO}:
            arguments = {
                key: value
                for key, value in {
                    "scenario_type": command.scenario_type,
                    "lane_count": command.lane_count,
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
                if value not in (None, False, "")
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
        self.tool_registry.register_tool(
            "generate_scenario",
            "生成或更新当前 SUMO 场景，可同时修改场景类型、车道、长度、限速、流量、时长、步长，并可在完成后直接运行。",
            {
                "type": "object",
                "properties": {
                    "scenario_type": {"type": "string", "enum": ["intersection", "t_junction", "corridor"]},
                    "lane_count": {"type": "integer", "minimum": 1},
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
            "更新用户默认偏好，包括默认场景、默认流量和默认仿真时长。",
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
        self.tool_registry.register_tool(
            "request_run",
            "请求运行当前项目的仿真。",
            {"type": "object", "properties": {}, "additionalProperties": False},
            self._tool_request_run,
        )
        self.tool_registry.register_tool(
            "summarize_project",
            "查看当前项目摘要。",
            {"type": "object", "properties": {}, "additionalProperties": False},
            self._tool_summarize_project,
        )
        self.tool_registry.register_tool(
            "show_history",
            "查看最近的操作历史。",
            {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "minimum": 1, "maximum": 20},
                },
                "additionalProperties": False,
            },
            self._tool_show_history,
        )
    def _build_local_chat_reply(
        self,
        text: str,
        project: ProjectContext | None,
        project_summary: str | None,
    ) -> str | None:
        lowered = text.lower().strip()
        if any(token in text for token in ("介绍你自己", "自我介绍", "你是谁", "你叫什么")):
            return build_intro_reply(project_summary)
        if any(token in text for token in ("你能做什么", "有什么用", "可以做什么", "能帮我做什么")):
            return build_capability_reply(project_summary)
        if any(token in text for token in ("怎么用", "怎么生成", "如何生成", "怎么创建", "给我个示例", "给我几个例子", "怎么操作")) or lowered in {"help", "usage"}:
            return build_how_to_reply(project_summary)
        if any(token in text for token in ("当前项目", "当前场景", "项目摘要", "现在是什么场景", "项目是什么")):
            if project is None:
                return "当前还没有打开项目。你可以先让我生成一个场景，或者先新建并加载项目。"
            state = self._derive_scenario_state(project, self.get_user_preferences())
            return self._format_project_summary(project, state)
        return None

    def _tool_generate_scenario(self, arguments: dict, runtime_context: dict[str, Any] | None = None) -> dict:
        project_context = None
        if runtime_context and runtime_context.get("project") is not None:
            runtime_project = runtime_context["project"]
            project_context = runtime_project if isinstance(runtime_project, ProjectContext) else ProjectContext.model_validate(runtime_project)

        command = ParsedCommand(
            intent=UserIntent.EDIT_SCENARIO if project_context is not None else UserIntent.CREATE_SCENARIO,
            scenario_type=arguments.get("scenario_type"),
            lane_count=arguments.get("lane_count"),
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
            message = (
                "我已经识别到你想修改场景，但当前缺少明确参数。\n"
                "你可以直接说：车道改为 5、流量提高 30%、时长改成 1200 秒。"
            )
            return {
                "reply_text": message,
                "updated_project": project_context.model_dump(mode="json") if project_context else None,
                "issues": ["未识别到可执行的修改参数。"],
                "operation_summary": "编辑失败：未识别到具体参数。",
                "before_state": base_state.model_dump(mode="json"),
                "after_state": base_state.model_dump(mode="json"),
            }

        next_state = self._apply_command_to_state(base_state, command, preferences)
        network = self.network_generator.generate(
            NetworkGenerationRequest(
                scenario_type=next_state.scenario_type,
                lane_count=next_state.lane_count,
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
        updated_context = ProjectContext(
            meta=meta,
            network=network,
            routes=routes,
            simulation=simulation,
            scenario_state=next_state,
        )
        build_result = self.project_builder.build_project(updated_context)
        issue_texts = [f"{issue.level}: {issue.message}" for issue in build_result.issues]
        has_build_errors = any(issue.level == "error" for issue in build_result.issues)

        operation_summary = self._build_state_change_summary(base_state if project_context else None, next_state)
        detail_summary = (
            f"当前目标场景：{self._label_scenario(next_state.scenario_type)}，"
            f"车道数={next_state.lane_count}，长度={int(round(next_state.road_length))}m，"
            f"限速={self._format_speed_limit(next_state.speed_limit)}，流量={self._describe_flow(next_state)}，"
            f"时长={next_state.duration_seconds}s，步长={next_state.step_length}。"
        )
        if next_state.traffic_bias:
            detail_summary += f" 偏向={self.BIAS_LABELS.get(next_state.traffic_bias, next_state.traffic_bias)}。"
        if command.should_run_simulation and not has_build_errors:
            detail_summary += " 构建完成后将直接运行仿真。"
        if issue_texts:
            detail_summary += " 注意：" + "；".join(issue_texts)

        reply_prefix = "场景构建失败" if has_build_errors else "场景已更新"
        reply_text = f"{reply_prefix}：\n{operation_summary}\n\n{detail_summary}"
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
        updates = {
            key: value
            for key, value in arguments.items()
            if key in {"default_scenario_type", "default_flow_level", "default_duration", "system_prompt_additions"}
            and value is not None
        }
        if not updates:
            return {
                "reply_text": "这次没有识别到可更新的偏好字段。支持默认场景、默认流量、默认时长和额外提示词。",
                "issues": [],
            }

        updated = current.model_copy(update=updates)
        self.config_store.save_user_preferences(updated)
        self.set_user_preferences(updated)
        confirmation_lines = [f"- {key}: {getattr(current, key)} -> {value}" for key, value in updates.items()]
        operation_summary = "\n".join(confirmation_lines)
        return {
            "reply_text": f"偏好已更新：\n{operation_summary}",
            "issues": [],
            "operation_summary": operation_summary,
        }

    def _tool_request_run(self, arguments: dict, runtime_context: dict[str, Any] | None = None) -> dict:
        project_context = None
        if runtime_context and runtime_context.get("project") is not None:
            runtime_project = runtime_context["project"]
            project_context = runtime_project if isinstance(runtime_project, ProjectContext) else ProjectContext.model_validate(runtime_project)
        if project_context is None:
            return {
                "reply_text": "当前没有项目上下文。请先生成场景或创建项目后再运行。",
                "issues": [],
                "operation_summary": "运行请求失败：缺少项目上下文。",
            }
        operation_summary = f"请求运行项目 {project_context.meta.name}。"
        return {
            "reply_text": f"运行确认：\n- 当前项目：{project_context.meta.name}\n- 状态：已接受运行请求",
            "should_run_simulation": True,
            "issues": [],
            "operation_summary": operation_summary,
            "before_state": project_context.scenario_state.model_dump(mode="json") if project_context.scenario_state else None,
            "after_state": project_context.scenario_state.model_dump(mode="json") if project_context.scenario_state else None,
        }

    def _tool_summarize_project(self, arguments: dict, runtime_context: dict[str, Any] | None = None) -> dict:
        project = None
        if runtime_context and runtime_context.get("project") is not None:
            runtime_project = runtime_context["project"]
            project = runtime_project if isinstance(runtime_project, ProjectContext) else ProjectContext.model_validate(runtime_project)
        if project is None:
            return {"reply_text": "当前没有项目上下文。请先生成场景或创建项目。", "issues": []}
        state = self._derive_scenario_state(project, self.get_user_preferences())
        operation_summary = f"查看项目摘要：{project.meta.name}"
        return {
            "reply_text": self._format_project_summary(project, state),
            "updated_project": project.model_dump(mode="json"),
            "issues": [],
            "operation_summary": operation_summary,
            "before_state": state.model_dump(mode="json"),
            "after_state": state.model_dump(mode="json"),
        }

    def _tool_show_history(self, arguments: dict, runtime_context: dict[str, Any] | None = None) -> dict:
        project = None
        if runtime_context and runtime_context.get("project") is not None:
            runtime_project = runtime_context["project"]
            project = runtime_project if isinstance(runtime_project, ProjectContext) else ProjectContext.model_validate(runtime_project)
        limit = int(arguments.get("limit", 5))
        records = self.history_store.list_recent(project_dir=project.meta.project_dir if project else None, limit=limit)
        if not records:
            return {"reply_text": "当前还没有可追溯的操作历史。", "issues": []}

        lines: list[str] = []
        title = f"最近 {len(records)} 条操作历史"
        if project is not None:
            title += f"（项目：{project.meta.name}）"
        lines.append(title)
        for index, record in enumerate(records, start=1):
            created_at = record.created_at.strftime("%Y-%m-%d %H:%M:%S")
            lines.append(f"{index}. [{created_at}] {record.intent}")
            lines.append(f"用户消息：{record.user_message}")
            lines.append(f"变更摘要：{record.change_summary}")
        return {"reply_text": "\n".join(lines), "issues": [], "operation_summary": title}
    def _derive_scenario_state(self, project: ProjectContext, preferences: UserPreferences) -> ProjectScenarioState:
        if project.scenario_state is not None:
            return project.scenario_state

        scenario_type = project.network.scenario_type if project.network else preferences.default_scenario_type
        lane_count = project.network.edges[0].num_lanes if project.network and project.network.edges else 2
        road_length = project.network.edges[0].length if project.network and project.network.edges and project.network.edges[0].length else 200.0
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

        lane_count = command.lane_count or base.lane_count
        if command.lane_delta is not None:
            lane_count = max(1, base.lane_count + command.lane_delta)

        return ProjectScenarioState(
            scenario_type=command.scenario_type or base.scenario_type,
            lane_count=lane_count,
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
        return self._parse_with_rules(text)

    def _parse_with_model(self, text: str, project: ProjectContext | None) -> ParsedCommand | None:
        return None
    def _parse_with_rules(self, text: str) -> ParsedCommand:
        command = ParsedCommand(intent=self.detect_intent(text))

        history_match = re.search(r"最近\s*(\d+)\s*条", text)
        if history_match:
            command.history_limit = int(history_match.group(1))

        if any(token in text for token in ("直接运行", "直接跑", "跑起来", "启动仿真", "并运行", "运行一下", "生成一次仿真")):
            command.should_run_simulation = True
        elif command.intent == UserIntent.RUN_SIMULATION:
            command.should_run_simulation = True

        scenario_map = {
            "十字路口": "intersection",
            "十字": "intersection",
            "T字": "t_junction",
            "t字": "t_junction",
            "丁字": "t_junction",
            "路段": "corridor",
            "直线": "corridor",
            "走廊": "corridor",
        }
        for token, scenario_type in scenario_map.items():
            if token in text:
                command.scenario_type = scenario_type
                break

        lane_match = re.search(r"([0-9一二两三四五六七八九十]+)车道", text)
        if lane_match:
            command.lane_count = self._parse_chinese_number(lane_match.group(1))
        else:
            lane_assignment_match = re.search(r"车道(?:数)?(?:改为|改成|设为|设置为|调整为|变为|=|增加到|减少到|升到|降到)?\s*([0-9一二两三四五六七八九十]+)", text)
            if lane_assignment_match:
                command.lane_count = self._parse_chinese_number(lane_assignment_match.group(1))

        lane_increase_match = re.search(r"(?:再)?(?:加|增加)\s*([0-9一二两三四五六七八九十]+)?\s*条?车道", text)
        lane_decrease_match = re.search(r"(?:再)?(?:减|减少)\s*([0-9一二两三四五六七八九十]+)?\s*条?车道", text)
        if command.lane_count is None and lane_increase_match and "到" not in lane_increase_match.group(0):
            raw = lane_increase_match.group(1)
            command.lane_delta = self._parse_chinese_number(raw) if raw else 1
        elif command.lane_count is None and lane_decrease_match and "到" not in lane_decrease_match.group(0):
            raw = lane_decrease_match.group(1)
            command.lane_delta = -(self._parse_chinese_number(raw) if raw else 1)

        length_match = re.search(r"(?:长度|路段长度|道路长度)(?:为|=|改成|设为|调整为)?\s*(\d+(?:\.\d+)?)\s*(?:米|m)?", text, re.IGNORECASE)
        if length_match:
            command.road_length = float(length_match.group(1))

        seconds_match = re.search(r"(\d+(?:\.\d+)?)\s*秒", text)
        minutes_match = re.search(r"(\d+(?:\.\d+)?)\s*(分钟|分)", text)
        hours_match = re.search(r"(\d+(?:\.\d+)?)\s*(小时|h)", text, re.IGNORECASE)
        if seconds_match:
            command.duration_seconds = int(float(seconds_match.group(1)))
        elif minutes_match:
            command.duration_seconds = int(float(minutes_match.group(1)) * 60)
        elif hours_match:
            command.duration_seconds = int(float(hours_match.group(1)) * 3600)

        step_match = re.search(r"步长(?:为|=|改成|设为|调整为)?\s*(\d+(?:\.\d+)?)", text)
        if step_match:
            command.step_length = float(step_match.group(1))

        seed_match = re.search(r"(?:种子|seed)(?:为|=|设为)?\s*(\d+)", text, re.IGNORECASE)
        if seed_match:
            command.seed = int(seed_match.group(1))

        speed_match = re.search(r"(?:限速|速度)(?:为|=|改成|设为|调整为)?\s*(\d+(?:\.\d+)?)\s*(km/h|kmh|公里/小时|m/s)?", text, re.IGNORECASE)
        if speed_match:
            speed_value = float(speed_match.group(1))
            unit = speed_match.group(2).lower() if speed_match.group(2) else ""
            if unit in {"km/h", "kmh", "公里/小时"}:
                speed_value = speed_value / 3.6
            command.speed_limit = round(speed_value, 2)

        explicit_flow_match = re.search(r"流量(?:为|=|改成|设为|调整为|到|增加到|提高到|降低到|减少到)?\s*(\d{2,5})\s*(?:辆/小时|veh/h|vph)?", text, re.IGNORECASE)
        has_explicit_flow_target = explicit_flow_match is not None
        if explicit_flow_match:
            command.flow_rate = int(explicit_flow_match.group(1))
            command.flow_level = self._infer_flow_level(command.flow_rate)

        increase_match = re.search(r"流量(?:提高|增加)\s*(\d+(?:\.\d+)?)%", text)
        decrease_match = re.search(r"流量(?:降低|减少)\s*(\d+(?:\.\d+)?)%", text)
        if not has_explicit_flow_target:
            if increase_match:
                command.flow_multiplier = 1.0 + float(increase_match.group(1)) / 100.0
            elif decrease_match:
                command.flow_multiplier = max(0.0, 1.0 - float(decrease_match.group(1)) / 100.0)
            elif any(token in text for token in ("增加流量", "提高流量", "加大流量", "流量增加", "流量提高", "流量调大", "流量调高", "把流量调大", "把流量调高", "流量大一点", "流量高一点")):
                command.flow_multiplier = 1.2
            elif any(token in text for token in ("减少流量", "降低流量", "减小流量", "流量减少", "流量降低", "流量调小", "流量调低", "把流量调小", "把流量调低", "流量小一点", "流量低一点")):
                command.flow_multiplier = 0.8
            elif any(token in text for token in ("流量稍微大一点", "流量稍大一点", "流量再大一点", "流量再高一点", "流量大一些", "流量高一些", "流量再提高一些", "流量再增加一些")):
                command.flow_multiplier = 1.1
            elif any(token in text for token in ("流量稍微小一点", "流量稍小一点", "流量再小一点", "流量再低一点", "流量小一些", "流量低一些", "流量再降低一些", "流量再减少一些")):
                command.flow_multiplier = 0.9
            elif any(direction in text for direction in ("南北", "东西")) and any(token in text for token in ("提高一些", "增加一些", "大一点", "高一点")):
                command.flow_multiplier = 1.1
            elif any(direction in text for direction in ("南北", "东西")) and any(token in text for token in ("降低一些", "减少一些", "小一点", "低一点")):
                command.flow_multiplier = 0.9

        if command.flow_level is None:
            if any(token in text for token in ("高流量", "高峰", "拥堵", "流量大")):
                command.flow_level = "high"
            elif any(token in text for token in ("低流量", "流量小", "稀疏")):
                command.flow_level = "low"
            elif any(token in text for token in ("中流量", "中等流量", "普通流量")):
                command.flow_level = "medium"

        if any(token in text for token in ("取消偏向", "清空偏向", "去掉偏向")):
            command.reset_traffic_bias = True
        elif "南北" in text:
            command.traffic_bias = "north_south"
        elif "东西" in text:
            command.traffic_bias = "east_west"

        if any(token in text for token in ("取消随机种子", "清空随机种子", "清空seed", "取消seed", "不要种子")):
            command.reset_seed = True

        if any(token in text for token in ("恢复默认流量", "流量恢复默认")):
            command.reset_flow_to_default = True
        if any(token in text for token in ("恢复默认时长", "时长恢复默认")):
            command.reset_duration_to_default = True
        if any(token in text for token in ("恢复默认步长", "步长恢复默认")):
            command.reset_step_length_to_default = True

        preference_updates: dict = {}
        if any(token in text for token in ("默认场景", "偏好场景")) and command.scenario_type and not any(token in text for token in ("恢复默认", "取消")):
            preference_updates["default_scenario_type"] = command.scenario_type
        if any(token in text for token in ("默认流量", "偏好流量")) and command.flow_level and not any(token in text for token in ("恢复默认", "取消")):
            preference_updates["default_flow_level"] = command.flow_level
        if any(token in text for token in ("默认时长", "默认仿真时长")) and command.duration_seconds and not any(token in text for token in ("恢复默认", "取消")):
            preference_updates["default_duration"] = command.duration_seconds
        if preference_updates:
            command.intent = UserIntent.UPDATE_PREFERENCES
            command.preference_updates = preference_updates

        project_name_match = re.search(r"项目(?:名|名称)(?:为|叫)?\s*([A-Za-z0-9_\-\u4e00-\u9fa5]+)", text)
        if project_name_match:
            command.project_name = project_name_match.group(1)

        return command

    @staticmethod
    def _parse_chinese_number(raw: str) -> int:
        if raw.isdigit():
            return int(raw)
        mapping = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
        if raw == "十":
            return 10
        if raw.startswith("十"):
            return 10 + mapping.get(raw[1], 0)
        if raw.endswith("十"):
            return mapping.get(raw[0], 0) * 10
        if "十" in raw:
            left, right = raw.split("十", 1)
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
        return any(
            value is not None
            for value in (
                command.scenario_type,
                command.lane_count,
                command.lane_delta,
                command.road_length,
                command.speed_limit,
                command.duration_seconds,
                command.step_length,
                command.flow_level,
                command.flow_rate,
                command.flow_multiplier,
                command.traffic_bias,
                command.seed,
            )
        ) or any(
            (
                command.reset_traffic_bias,
                command.reset_seed,
                command.reset_flow_to_default,
                command.reset_duration_to_default,
                command.reset_step_length_to_default,
            )
        )

    @staticmethod
    def _extract_json_object(text: str) -> dict | None:
        if not text:
            return None
        stripped = text.strip()
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            pass
        match = re.search(r"\{.*\}", stripped, re.DOTALL)
        if not match:
            return None
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None

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

        self._emit_progress(progress_callback, "理解中", f"{ASSISTANT_NAME} 正在理解你的需求...")
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

        self._emit_progress(progress_callback, "规划中", f"{ASSISTANT_NAME} 正在规划回复和工具...")
        decision = self._decide_response(text, project, context_parts)
        if decision.mode == "chat":
            fallback_command = self._parse_command(text, project)
            reply_text = decision.reply_text.strip() or self._fallback_reply(fallback_command, project)
            result = AgentExecutionResult(
                reply_text=reply_text,
                updated_project=project,
                issues=list(decision.issues),
                response_mode="chat",
                assistant_name=ASSISTANT_NAME,
            )
            self.memory.append_agent_message(result.reply_text)
            return result

        self._emit_progress(progress_callback, "执行中", f"{ASSISTANT_NAME} 正在执行工具...")
        tool_summaries, result = self.execute_tool_plan(decision.tool_calls, project)
        for issue in decision.issues:
            if issue not in result.issues:
                result.issues.append(issue)

        self._emit_progress(progress_callback, "整理结果", f"{ASSISTANT_NAME} 正在整理结果...")
        result.reply_text = self.summarize_result(text, result.updated_project or project, tool_summaries, result.issues)
        history_command = self._build_history_command(text, project, decision.tool_calls)
        history_record = self._record_operation(history_command, text, project, result)
        if history_record is not None:
            result.history_record_id = history_record.id
            result.reply_text = chr(10).join([result.reply_text, "", f"已记录到操作历史：#{history_record.id}"])

        combined_summary = " | ".join(item.summary for item in tool_summaries if item.summary)
        if combined_summary:
            self.memory.append_tool_summary(combined_summary)
        self.memory.append_agent_message(result.reply_text)
        return result

    def detect_intent(self, text: str) -> UserIntent:
        lowered = text.lower()
        has_edit = any(token in text for token in ("改成", "修改", "调整", "提高", "增加", "降低", "减少", "设为", "取消", "清空", "恢复默认", "去掉"))
        has_scenario = any(token in text for token in ("生成", "创建", "新建", "十字", "T字", "t字", "丁字", "路口", "路段"))
        has_param = any(token in text for token in ("流量", "步长", "时长", "车道", "限速", "速度", "seed", "种子", "长度", "偏向", "南北", "东西"))
        has_run = any(token in text for token in ("运行", "启动", "跑", "开始仿真")) or "run" in lowered
        has_summary = any(token in text for token in ("当前项目", "项目情况", "当前场景", "场景摘要", "总结当前", "现在是什么场景", "看下当前"))
        has_history = any(token in text for token in ("操作历史", "最近变更", "查看历史", "历史记录", "最近操作", "追溯记录"))
        has_pref_words = any(token in text for token in ("偏好", "默认场景", "默认流量", "默认时长", "习惯"))

        if has_history:
            return UserIntent.VIEW_HISTORY
        if has_summary and not (has_edit or has_run or has_scenario):
            return UserIntent.SUMMARIZE_PROJECT
        if has_pref_words and not has_edit:
            return UserIntent.UPDATE_PREFERENCES
        if has_edit and (has_param or has_scenario):
            return UserIntent.EDIT_SCENARIO
        if has_scenario:
            return UserIntent.CREATE_SCENARIO
        if has_param:
            return UserIntent.EDIT_SCENARIO
        if has_run:
            return UserIntent.RUN_SIMULATION
        return UserIntent.UNKNOWN

    def _build_local_chat_reply(
        self,
        text: str,
        project: ProjectContext | None,
        project_summary: str | None,
    ) -> str | None:
        lowered = text.lower().strip()
        if any(token in text for token in ("介绍你自己", "自我介绍", "你是谁", "你叫什么")):
            return build_intro_reply(project_summary)
        if any(token in text for token in ("你能做什么", "有什么用", "可以做什么", "能帮我做什么")):
            return build_capability_reply(project_summary)
        if any(token in text for token in ("怎么用", "怎么生成", "如何生成", "怎么创建", "给我个示例", "给我几个例子", "怎么操作")) or lowered in {"help", "usage"}:
            return build_how_to_reply(project_summary)
        if any(token in text for token in ("当前项目", "当前场景", "项目摘要", "现在是什么场景", "项目是什么")):
            if project is None:
                return "当前还没有打开项目。你可以先让我生成一个场景，或者先新建并加载项目。"
            state = self._derive_scenario_state(project, self.get_user_preferences())
            return self._format_project_summary(project, state)
        return None
    def _tool_generate_scenario(self, arguments: dict, runtime_context: dict[str, Any] | None = None) -> dict:
        project_context = None
        if runtime_context and runtime_context.get("project") is not None:
            runtime_project = runtime_context["project"]
            project_context = runtime_project if isinstance(runtime_project, ProjectContext) else ProjectContext.model_validate(runtime_project)

        command = ParsedCommand(
            intent=UserIntent.EDIT_SCENARIO if project_context is not None else UserIntent.CREATE_SCENARIO,
            scenario_type=arguments.get("scenario_type"),
            lane_count=arguments.get("lane_count"),
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
            message = chr(10).join(
                [
                    "我已经识别到你想修改场景，但当前缺少明确参数。",
                    "你可以直接说：车道改为 5、流量提高 30%、时长改成 1200 秒。",
                ]
            )
            return {
                "reply_text": message,
                "updated_project": project_context.model_dump(mode="json") if project_context else None,
                "issues": ["未识别到可执行的修改参数。"],
                "operation_summary": "编辑失败：未识别到具体参数。",
                "before_state": base_state.model_dump(mode="json"),
                "after_state": base_state.model_dump(mode="json"),
            }

        next_state = self._apply_command_to_state(base_state, command, preferences)
        network = self.network_generator.generate(
            NetworkGenerationRequest(
                scenario_type=next_state.scenario_type,
                lane_count=next_state.lane_count,
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
        updated_context = ProjectContext(
            meta=meta,
            network=network,
            routes=routes,
            simulation=simulation,
            scenario_state=next_state,
        )
        build_result = self.project_builder.build_project(updated_context)
        issue_texts = [f"{issue.level}: {issue.message}" for issue in build_result.issues]
        has_build_errors = any(issue.level == "error" for issue in build_result.issues)

        operation_summary = self._build_state_change_summary(base_state if project_context else None, next_state)
        detail_summary = (
            f"当前目标场景：{self._label_scenario(next_state.scenario_type)}，"
            f"车道数={next_state.lane_count}，长度={int(round(next_state.road_length))}m，"
            f"限速={self._format_speed_limit(next_state.speed_limit)}，流量={self._describe_flow(next_state)}，"
            f"时长={next_state.duration_seconds}s，步长={next_state.step_length}。"
        )
        if next_state.traffic_bias:
            detail_summary += f" 偏向={self.BIAS_LABELS.get(next_state.traffic_bias, next_state.traffic_bias)}。"
        if command.should_run_simulation and not has_build_errors:
            detail_summary += " 构建完成后将直接运行仿真。"
        if issue_texts:
            detail_summary += " 注意：" + "；".join(issue_texts)

        reply_prefix = "场景构建失败" if has_build_errors else "场景已更新"
        reply_text = chr(10).join([f"{reply_prefix}：", operation_summary, "", detail_summary])
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
        updates = {
            key: value
            for key, value in arguments.items()
            if key in {"default_scenario_type", "default_flow_level", "default_duration", "system_prompt_additions"}
            and value is not None
        }
        if not updates:
            return {
                "reply_text": "这次没有识别到可更新的偏好字段。支持默认场景、默认流量、默认时长和额外提示词。",
                "issues": [],
            }

        updated = current.model_copy(update=updates)
        self.config_store.save_user_preferences(updated)
        self.set_user_preferences(updated)
        confirmation_lines = [f"- {key}: {getattr(current, key)} -> {value}" for key, value in updates.items()]
        operation_summary = chr(10).join(confirmation_lines)
        return {
            "reply_text": chr(10).join(["偏好已更新：", operation_summary]),
            "issues": [],
            "operation_summary": operation_summary,
        }
    def _tool_request_run(self, arguments: dict, runtime_context: dict[str, Any] | None = None) -> dict:
        project_context = None
        if runtime_context and runtime_context.get("project") is not None:
            runtime_project = runtime_context["project"]
            project_context = runtime_project if isinstance(runtime_project, ProjectContext) else ProjectContext.model_validate(runtime_project)
        if project_context is None:
            return {
                "reply_text": "当前没有项目上下文。请先生成场景或创建项目后再运行。",
                "issues": [],
                "operation_summary": "运行请求失败：缺少项目上下文。",
            }
        operation_summary = f"请求运行项目 {project_context.meta.name}。"
        return {
            "reply_text": chr(10).join(["运行确认：", f"- 当前项目：{project_context.meta.name}", "- 状态：已接受运行请求"]),
            "should_run_simulation": True,
            "issues": [],
            "operation_summary": operation_summary,
            "before_state": project_context.scenario_state.model_dump(mode="json") if project_context.scenario_state else None,
            "after_state": project_context.scenario_state.model_dump(mode="json") if project_context.scenario_state else None,
        }

    def _tool_summarize_project(self, arguments: dict, runtime_context: dict[str, Any] | None = None) -> dict:
        project = None
        if runtime_context and runtime_context.get("project") is not None:
            runtime_project = runtime_context["project"]
            project = runtime_project if isinstance(runtime_project, ProjectContext) else ProjectContext.model_validate(runtime_project)
        if project is None:
            return {"reply_text": "当前没有项目上下文。请先生成场景或创建项目。", "issues": []}
        state = self._derive_scenario_state(project, self.get_user_preferences())
        operation_summary = f"查看项目摘要：{project.meta.name}"
        return {
            "reply_text": self._format_project_summary(project, state),
            "updated_project": project.model_dump(mode="json"),
            "issues": [],
            "operation_summary": operation_summary,
            "before_state": state.model_dump(mode="json"),
            "after_state": state.model_dump(mode="json"),
        }

    def _tool_show_history(self, arguments: dict, runtime_context: dict[str, Any] | None = None) -> dict:
        project = None
        if runtime_context and runtime_context.get("project") is not None:
            runtime_project = runtime_context["project"]
            project = runtime_project if isinstance(runtime_project, ProjectContext) else ProjectContext.model_validate(runtime_project)
        limit = int(arguments.get("limit", 5))
        records = self.history_store.list_recent(project_dir=project.meta.project_dir if project else None, limit=limit)
        if not records:
            return {"reply_text": "当前还没有可追溯的操作历史。", "issues": []}

        lines: list[str] = []
        title = f"最近 {len(records)} 条操作历史"
        if project is not None:
            title += f"（项目：{project.meta.name}）"
        lines.append(title)
        for index, record in enumerate(records, start=1):
            created_at = record.created_at.strftime("%Y-%m-%d %H:%M:%S")
            lines.append(f"{index}. [{created_at}] {record.intent}")
            lines.append(f"用户消息：{record.user_message}")
            lines.append(f"变更摘要：{record.change_summary}")
        return {"reply_text": chr(10).join(lines), "issues": [], "operation_summary": title}

    def _fallback_reply(self, command: ParsedCommand, project: ProjectContext | None) -> str:
        if command.intent == UserIntent.RUN_SIMULATION:
            if project is None:
                return "当前没有项目上下文。请先生成场景，或先新建项目后再运行。"
            return f"已收到运行请求，当前项目是 {project.meta.name}。"
        if command.intent == UserIntent.SUMMARIZE_PROJECT:
            if project is None:
                return "当前没有项目上下文。请先生成场景或创建项目。"
            return self._format_project_summary(project, self._derive_scenario_state(project, self.get_user_preferences()))
        if command.intent == UserIntent.VIEW_HISTORY:
            return "你可以直接说“看看最近 5 条历史”或“查看操作历史”，我会帮你整理最近的项目变更。"
        if command.intent == UserIntent.UPDATE_PREFERENCES:
            return "你可以直接说“以后默认场景用十字路口”或“默认时长改成 1200 秒”，我会帮你更新偏好。"
        if command.intent in {UserIntent.CREATE_SCENARIO, UserIntent.EDIT_SCENARIO} and not self._has_edit_payload(command):
            return "我已经识别到你在描述场景，但还缺少可执行参数。你可以补一句：车道改为 4、流量提高 30%、仿真 1800 秒。"
        if project is not None:
            return chr(10).join(
                [
                    f"我是 {ASSISTANT_NAME}，主要负责 TrafficAgent 里的场景生成、参数调整、项目摘要、历史查询和仿真运行。",
                    "",
                    "当前项目概览：",
                    self._format_project_summary(project, self._derive_scenario_state(project, self.get_user_preferences())),
                ]
            )
        return (
            f"我是 {ASSISTANT_NAME}，主要负责 TrafficAgent 里的场景生成、参数调整、项目摘要、历史查询和仿真运行。"
            "你可以直接告诉我你想做什么，例如：生成一个双向四车道十字路口，仿真 1800 秒。"
        )

    def _fallback_tool_reply(
        self,
        user_text: str,
        project: ProjectContext | None,
        tool_summaries: list[ToolExecutionSummary],
        issues: list[str],
    ) -> str:
        lines = [f"我理解你的意思是：{user_text}", "本轮我已经完成这些动作："]
        lines.extend(f"- {item.summary}" for item in tool_summaries if item.summary)
        if project is not None:
            lines.extend(
                [
                    "",
                    "当前项目状态：",
                    self._format_project_summary(project, self._derive_scenario_state(project, self.get_user_preferences())),
                ]
            )
        if issues:
            lines.append("")
            lines.append("需要注意：")
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
        name = project.meta.name
        bias = self.BIAS_LABELS.get(state.traffic_bias, state.traffic_bias or "无")
        seed = state.seed if state.seed is not None else "auto"
        file_count = 0
        if project.network:
            file_count += 2
        if project.routes:
            file_count += 1
        if project.simulation:
            file_count += 2
        return (
            f"当前项目：{name}\n"
            f"场景={self._label_scenario(state.scenario_type)}，车道数={state.lane_count}，长度={int(round(state.road_length))}m，限速={self._format_speed_limit(state.speed_limit)}\n"
            f"流量={self._describe_flow(state)}，偏向={bias}\n"
            f"时长={state.duration_seconds}s，步长={state.step_length}，seed={seed}\n"
            f"上下文完整度：network={'yes' if project.network else 'no'}，routes={'yes' if project.routes else 'no'}，simulation={'yes' if project.simulation else 'no'}，预期输出文件数={file_count}"
        )

    def _build_state_change_summary(self, before: ProjectScenarioState | None, after: ProjectScenarioState) -> str:
        if before is None:
            return (
                f"- 已创建场景：{self._label_scenario(after.scenario_type)}\n"
                f"- 车道数：{after.lane_count}\n"
                f"- 道路长度：{int(round(after.road_length))}m\n"
                f"- 限速：{self._format_speed_limit(after.speed_limit)}\n"
                f"- 流量：{self._describe_flow(after)}\n"
                f"- 仿真时长：{after.duration_seconds}s\n"
                f"- 仿真步长：{after.step_length}"
            )

        changes = self._collect_state_changes(before, after)
        if not changes:
            return "- 未检测到参数变化，已按当前状态重新生成 SUMO 文件。"
        return "\n".join(f"- {item}" for item in changes)

    def _collect_state_changes(self, before: ProjectScenarioState, after: ProjectScenarioState) -> list[str]:
        changes: list[str] = []
        before_dict = before.model_dump(mode="json")
        after_dict = after.model_dump(mode="json")
        for field in self.STATE_FIELD_LABELS:
            if before_dict.get(field) == after_dict.get(field):
                continue
            label = self.STATE_FIELD_LABELS[field]
            changes.append(f"{label}: {self._format_state_value(field, before_dict.get(field))} -> {self._format_state_value(field, after_dict.get(field))}")
        return changes

    def _format_state_value(self, field: str, value) -> str:
        if field == "scenario_type":
            return self._label_scenario(value)
        if field == "road_length":
            return f"{int(round(float(value)))}m"
        if field == "speed_limit":
            return self._format_speed_limit(float(value))
        if field == "flow_rate":
            return "auto" if value is None else f"{int(value)} veh/h"
        if field == "traffic_bias":
            return self.BIAS_LABELS.get(value, value or "无")
        if field == "duration_seconds":
            return f"{int(value)}s"
        if field == "step_length":
            return str(value)
        if field == "seed":
            return "auto" if value is None else str(value)
        return str(value)

    def _label_scenario(self, scenario_type: str | None) -> str:
        if scenario_type is None:
            return "未设置"
        return self.SCENARIO_LABELS.get(scenario_type, scenario_type)

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
            return "收到运行请求。"
        if command.intent == UserIntent.SUMMARIZE_PROJECT:
            return "查看当前项目摘要。"
        if command.intent == UserIntent.UPDATE_PREFERENCES:
            return "更新用户偏好。"
        return result.reply_text.splitlines()[0] if result.reply_text else command.intent.value

















