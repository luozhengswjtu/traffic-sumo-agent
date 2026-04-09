from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Callable

from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.base import TaskResult
from autogen_agentchat.messages import ModelClientStreamingChunkEvent
from autogen_core.tools import FunctionTool

from agent.tool_registry import ToolRegistry
from model_providers.base import ToolCall
from sumo_domain.preferences import ModelConfig


@dataclass(slots=True)
class AutoGenToolRun:
    tool_call: ToolCall
    result: dict[str, Any]


@dataclass(slots=True)
class AutoGenRunResult:
    reply_text: str = ""
    tool_runs: list[AutoGenToolRun] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)


class AutoGenAssistantBridge:
    def __init__(
        self,
        tool_registry: ToolRegistry,
        model_client_factory,
        get_model_config: Callable[[], ModelConfig],
        normalize_tool_arguments: Callable[[str, dict[str, Any]], dict[str, Any]],
        format_error: Callable[[str], str],
    ) -> None:
        self.tool_registry = tool_registry
        self.model_client_factory = model_client_factory
        self.get_model_config = get_model_config
        self.normalize_tool_arguments = normalize_tool_arguments
        self.format_error = format_error

    def run(
        self,
        text: str,
        system_message: str,
        runtime_context: dict[str, Any] | None = None,
        stream_callback: Callable[[str], None] | None = None,
    ) -> AutoGenRunResult:
        return asyncio.run(
            self._run_async(
                text=text,
                system_message=system_message,
                runtime_context=runtime_context,
                stream_callback=stream_callback,
            )
        )

    async def _run_async(
        self,
        text: str,
        system_message: str,
        runtime_context: dict[str, Any] | None = None,
        stream_callback: Callable[[str], None] | None = None,
    ) -> AutoGenRunResult:
        tool_runs: list[AutoGenToolRun] = []
        issues: list[str] = []
        current_context = dict(runtime_context or {})
        client = self.model_client_factory.create_raw_client(self.get_model_config())
        try:
            agent = AssistantAgent(
                name="traffic_agent",
                model_client=client,
                tools=self._build_tools(tool_runs, issues, current_context),
                system_message=system_message,
                model_client_stream=stream_callback is not None,
                reflect_on_tool_use=False,
                max_tool_iterations=1,
                tool_call_summary_format="{result}",
            )
            if stream_callback is None:
                task_result = await agent.run(task=text)
            else:
                task_result = await self._run_with_stream(agent, text, stream_callback)
        finally:
            await client.close()
        return AutoGenRunResult(
            reply_text=self._extract_reply_text(task_result),
            tool_runs=tool_runs,
            issues=issues,
        )

    @staticmethod
    async def _run_with_stream(
        agent: AssistantAgent,
        text: str,
        stream_callback: Callable[[str], None],
    ) -> TaskResult:
        task_result: TaskResult | None = None
        async for item in agent.run_stream(task=text, output_task_messages=False):
            if isinstance(item, ModelClientStreamingChunkEvent):
                if item.content:
                    stream_callback(str(item.content))
                continue
            if isinstance(item, TaskResult):
                task_result = item
        if task_result is None:
            raise RuntimeError("模型未返回最终结果。")
        return task_result

    def _build_tools(
        self,
        tool_runs: list[AutoGenToolRun],
        issues: list[str],
        runtime_context: dict[str, Any],
    ) -> list[FunctionTool]:
        def invoke_tool(name: str, arguments: dict[str, Any]) -> str:
            normalized_arguments = self.normalize_tool_arguments(
                name,
                {key: value for key, value in arguments.items() if value is not None},
            )
            try:
                tool_result = self.tool_registry.invoke(name, normalized_arguments, runtime_context)
            except Exception as exc:
                message = f"工具 {name} 执行失败：{self.format_error(str(exc) or exc.__class__.__name__)}"
                issues.append(message)
                tool_result = {
                    "reply_text": message,
                    "issues": [message],
                    "operation_summary": message,
                }

            tool_runs.append(
                AutoGenToolRun(
                    tool_call=ToolCall(name=name, arguments=normalized_arguments),
                    result=tool_result,
                )
            )
            if tool_result.get("updated_project") is not None:
                runtime_context["project"] = tool_result["updated_project"]
            return str(
                tool_result.get("operation_summary")
                or tool_result.get("reply_text")
                or f"已执行 {name}"
            )

        def generate_scenario(
            scenario_type: str | None = None,
            lane_count: int | None = None,
            directional_lanes: dict[str, int] | None = None,
            lane_delta: int | None = None,
            road_length: float | None = None,
            speed_limit_kmh: float | None = None,
            speed_limit: float | None = None,
            duration_seconds: int | None = None,
            step_length: float | None = None,
            flow_level: str | None = None,
            flow_rate: int | None = None,
            flow_multiplier: float | None = None,
            traffic_bias: str | None = None,
            seed: int | None = None,
            signal_enabled: bool | None = None,
            signal_plan_name: str | None = None,
            signal_cycle_seconds: int | None = None,
            signal_offset_seconds: int | None = None,
            signal_yellow_seconds: int | None = None,
            signal_all_red_seconds: int | None = None,
            signal_ns_green_seconds: int | None = None,
            signal_ew_green_seconds: int | None = None,
            reset_traffic_bias: bool | None = None,
            reset_seed: bool | None = None,
            reset_flow_to_default: bool | None = None,
            reset_duration_to_default: bool | None = None,
            reset_step_length_to_default: bool | None = None,
            reset_signal_plan: bool | None = None,
            should_run_simulation: bool | None = None,
            project_name: str | None = None,
        ) -> str:
            return invoke_tool(
                "generate_scenario",
                {
                    "scenario_type": scenario_type,
                    "lane_count": lane_count,
                    "directional_lanes": directional_lanes,
                    "lane_delta": lane_delta,
                    "road_length": road_length,
                    "speed_limit_kmh": speed_limit_kmh,
                    "speed_limit": speed_limit,
                    "duration_seconds": duration_seconds,
                    "step_length": step_length,
                    "flow_level": flow_level,
                    "flow_rate": flow_rate,
                    "flow_multiplier": flow_multiplier,
                    "traffic_bias": traffic_bias,
                    "seed": seed,
                    "signal_enabled": signal_enabled,
                    "signal_plan_name": signal_plan_name,
                    "signal_cycle_seconds": signal_cycle_seconds,
                    "signal_offset_seconds": signal_offset_seconds,
                    "signal_yellow_seconds": signal_yellow_seconds,
                    "signal_all_red_seconds": signal_all_red_seconds,
                    "signal_ns_green_seconds": signal_ns_green_seconds,
                    "signal_ew_green_seconds": signal_ew_green_seconds,
                    "reset_traffic_bias": reset_traffic_bias,
                    "reset_seed": reset_seed,
                    "reset_flow_to_default": reset_flow_to_default,
                    "reset_duration_to_default": reset_duration_to_default,
                    "reset_step_length_to_default": reset_step_length_to_default,
                    "reset_signal_plan": reset_signal_plan,
                    "should_run_simulation": should_run_simulation,
                    "project_name": project_name,
                },
            )

        def update_preferences(
            default_scenario_type: str | None = None,
            default_flow_level: str | None = None,
            default_duration: int | None = None,
            system_prompt_additions: str | None = None,
        ) -> str:
            return invoke_tool(
                "update_preferences",
                {
                    "default_scenario_type": default_scenario_type,
                    "default_flow_level": default_flow_level,
                    "default_duration": default_duration,
                    "system_prompt_additions": system_prompt_additions,
                },
            )

        def request_run() -> str:
            return invoke_tool("request_run", {})

        def summarize_project() -> str:
            return invoke_tool("summarize_project", {})

        def show_history(limit: int = 5) -> str:
            return invoke_tool("show_history", {"limit": limit})

        return [
            FunctionTool(
                generate_scenario,
                description=self.tool_registry.get_tool("generate_scenario").description,
                name="generate_scenario",
            ),
            FunctionTool(
                update_preferences,
                description=self.tool_registry.get_tool("update_preferences").description,
                name="update_preferences",
            ),
            FunctionTool(
                request_run,
                description=self.tool_registry.get_tool("request_run").description,
                name="request_run",
            ),
            FunctionTool(
                summarize_project,
                description=self.tool_registry.get_tool("summarize_project").description,
                name="summarize_project",
            ),
            FunctionTool(
                show_history,
                description=self.tool_registry.get_tool("show_history").description,
                name="show_history",
            ),
        ]

    @staticmethod
    def _extract_reply_text(task_result: TaskResult) -> str:
        for message in reversed(task_result.messages):
            content = getattr(message, "content", None)
            if isinstance(content, str) and content.strip():
                return content.strip()
        return ""
