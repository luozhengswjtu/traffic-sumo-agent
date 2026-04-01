from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QSplitter,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from agent.orchestrator import AgentExecutionResult
from sumo_domain.project_spec import ProjectContext, ProjectMeta, ProjectScenarioState, RecentProjectItem
from sumo_domain.simulation_spec import SimulationSpec
from sumo_tools.config_generator import SimulationConfigRequest
from sumo_tools.network_generator import NetworkGenerationRequest
from sumo_tools.route_generator import RouteGenerationRequest
from ui.chat_panel import ChatPanel
from ui.control_panel import ControlPanel
from ui.history_panel import HistoryPanel
from ui.project_dialog import NewProjectDialog
from ui.settings_dialog import SettingsDialog
from ui.sim_status_panel import SimulationStatusPanel


class MainWindow(QMainWindow):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.container = None
        self.current_project_meta: ProjectMeta | None = None
        self.current_project_context: ProjectContext | None = None
        self.current_simulation_spec = SimulationSpec()
        self.setWindowTitle("TrafficAgent")
        self.resize(1360, 820)
        self._build_ui()
        self._build_menu()

    def bind_services(self, container) -> None:
        self.container = container
        self.current_simulation_spec = SimulationSpec(end_time=container.user_preferences.default_duration)
        self.control_panel.load_simulation_spec(self.current_simulation_spec)
        self.container.sim_runner.stateChanged.connect(self.sim_status_panel.update_state)
        self.container.sim_runner.logProduced.connect(self.append_log)
        self.container.sim_runner.runFailed.connect(self.show_error)
        self.history_panel.clear_records()
        self.append_log("基础服务已绑定。")
        self.statusBar().showMessage("准备就绪")

    def _build_ui(self) -> None:
        splitter = QSplitter()

        self.chat_panel = ChatPanel()
        self.chat_panel.messageSubmitted.connect(self._handle_chat_message)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)

        self.control_panel = ControlPanel()
        self.control_panel.runRequested.connect(self._handle_run_requested)
        self.control_panel.pauseRequested.connect(self._handle_pause_requested)
        self.control_panel.resumeRequested.connect(self._handle_resume_requested)
        self.control_panel.stepRequested.connect(self._handle_step_requested)
        self.control_panel.stopRequested.connect(self._handle_stop_requested)
        self.control_panel.simulationParamsChanged.connect(self._handle_simulation_params_changed)

        self.sim_status_panel = SimulationStatusPanel()
        self.history_panel = HistoryPanel()
        self.history_panel.refreshRequested.connect(self._refresh_history_panel)

        self.log_output = QPlainTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setPlaceholderText("这里会显示执行日志、项目创建记录和后续仿真输出。")

        right_layout.addWidget(self.control_panel)
        right_layout.addWidget(self.sim_status_panel)
        right_layout.addWidget(self.history_panel, 3)
        right_layout.addWidget(self.log_output, 2)

        splitter.addWidget(self.chat_panel)
        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        wrapper = QWidget()
        wrapper_layout = QVBoxLayout(wrapper)
        wrapper_layout.addWidget(splitter)
        self.setCentralWidget(wrapper)

        status = QStatusBar()
        self.setStatusBar(status)

    def _build_menu(self) -> None:
        menu = self.menuBar()
        file_menu = menu.addMenu("文件")
        settings_menu = menu.addMenu("设置")
        view_menu = menu.addMenu("视图")

        new_project_action = QAction("新建项目", self)
        new_project_action.triggered.connect(self._create_project)
        file_menu.addAction(new_project_action)

        settings_action = QAction("模型与偏好设置", self)
        settings_action.triggered.connect(self._open_settings)
        settings_menu.addAction(settings_action)

        refresh_history_action = QAction("刷新操作历史", self)
        refresh_history_action.triggered.connect(self._refresh_history_panel)
        view_menu.addAction(refresh_history_action)

    def load_project(self, path: Path) -> None:
        if self.container is None:
            self.show_error("服务尚未初始化，暂时无法加载项目。")
            return

        try:
            meta = self.container.project_store.open_project(path)
        except FileNotFoundError as exc:
            self.show_error(str(exc))
            return

        self.current_project_meta = meta
        self.current_project_context = ProjectContext(meta=meta, simulation=self.current_simulation_spec)
        self.append_log(f"已加载项目：{meta.name}")
        self.statusBar().showMessage(f"当前项目：{meta.name}")
        self._remember_recent_project(meta)
        self._refresh_history_panel()

    def refresh_project_view(self) -> None:
        if self.current_project_meta is None:
            self.statusBar().showMessage("尚未打开项目")
            return
        self.statusBar().showMessage(f"当前项目：{self.current_project_meta.name}")

    def append_log(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_output.appendPlainText(f"[{timestamp}] {message}")

    def show_error(self, message: str) -> None:
        QMessageBox.critical(self, "错误", message)
        self.append_log(f"错误：{message}")

    def _create_project(self) -> None:
        if self.container is None:
            self.show_error("服务尚未初始化，暂时无法创建项目。")
            return

        dialog = NewProjectDialog(self.container.paths.projects_dir, self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return

        name = dialog.collect_project_name()
        base_dir = dialog.collect_project_path()
        if not name:
            self.show_error("项目名称不能为空。")
            return

        meta = self.container.project_store.create_project(name, base_dir)
        self.current_project_meta = meta
        self.current_project_context = ProjectContext(
            meta=meta,
            simulation=self.current_simulation_spec,
            scenario_state=ProjectScenarioState(
                scenario_type=self.container.user_preferences.default_scenario_type,
                flow_level=self.container.user_preferences.default_flow_level,
                duration_seconds=self.current_simulation_spec.end_time,
                step_length=self.current_simulation_spec.step_length,
                seed=self.current_simulation_spec.seed,
            ),
        )
        self.append_log(f"已创建项目：{meta.name}")
        self.statusBar().showMessage(f"当前项目：{meta.name}")
        self._remember_recent_project(meta)
        self._refresh_history_panel()

    def _open_settings(self) -> None:
        if self.container is None:
            self.show_error("服务尚未初始化，暂时无法打开设置。")
            return

        dialog = SettingsDialog(self)
        dialog.load_settings(self.container.model_config, self.container.user_preferences)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return

        self.container.model_config = dialog.collect_model_config()
        self.container.user_preferences = dialog.collect_user_preferences()
        self.container.config_store.save_model_config(self.container.model_config)
        self.container.config_store.save_user_preferences(self.container.user_preferences)
        self.append_log("已保存模型配置和用户偏好。")

    def _handle_chat_message(self, text: str) -> None:
        if self.container is None:
            self.show_error("服务尚未初始化。")
            return

        self.chat_panel.set_busy(True)
        try:
            result = self.container.agent_orchestrator.handle_user_message(text, self.current_project_context)
        finally:
            self.chat_panel.set_busy(False)

        self.chat_panel.append_agent_message(result.reply_text)
        self._apply_agent_result(result)

    def _handle_run_requested(self) -> None:
        if self.container is None:
            self.show_error("服务尚未初始化。")
            return
        if self.current_project_meta is None:
            self.show_error("请先创建或加载项目。")
            return
        if not self._ensure_project_built():
            return

        self.append_log("收到运行请求，准备通过 TraCI 启动 SUMO。")
        self.container.sim_runner.start_project(Path(self.current_project_meta.project_dir))

    def _handle_pause_requested(self) -> None:
        if self.container is None:
            return
        self.container.sim_runner.pause()

    def _handle_resume_requested(self) -> None:
        if self.container is None:
            return
        self.container.sim_runner.resume()

    def _handle_step_requested(self) -> None:
        if self.container is None:
            return
        self.container.sim_runner.step_once()

    def _handle_stop_requested(self) -> None:
        if self.container is None:
            return
        self.container.sim_runner.stop()

    def _handle_simulation_params_changed(self, spec: SimulationSpec) -> None:
        self.current_simulation_spec = spec
        if self.current_project_context is not None:
            scenario_state = self.current_project_context.scenario_state
            if scenario_state is not None:
                scenario_state = scenario_state.model_copy(
                    update={
                        "duration_seconds": spec.end_time,
                        "step_length": spec.step_length,
                        "seed": spec.seed,
                    }
                )
            self.current_project_context = self.current_project_context.model_copy(
                update={"simulation": spec, "scenario_state": scenario_state}
            )
        self.append_log(f"参数已更新：时长={spec.end_time}s, 步长={spec.step_length}, seed={spec.seed}")

    def _apply_agent_result(self, result: AgentExecutionResult) -> None:
        if result.updated_project is not None:
            self.current_project_context = result.updated_project
            self.current_project_meta = result.updated_project.meta
            self.current_simulation_spec = result.updated_project.simulation or self.current_simulation_spec
            self.control_panel.load_simulation_spec(self.current_simulation_spec)
            self.statusBar().showMessage(f"当前项目：{self.current_project_meta.name}")
            self._remember_recent_project(self.current_project_meta)

        if result.operation_summary:
            self.append_log(f"变更确认：{result.operation_summary.replace(chr(10), ' | ')}")
        if result.history_record_id is not None:
            self.append_log(f"已写入操作历史：#{result.history_record_id}")

        for file_path in result.generated_files:
            self.append_log(f"已生成文件：{file_path}")
        for issue in result.issues:
            self.append_log(f"{issue}")

        self._refresh_history_panel(result.history_record_id)

        if result.should_run_simulation:
            if self.current_project_meta is None:
                self.show_error("当前没有可运行的项目。")
                return
            if not self._ensure_project_built():
                return
            self.append_log("Agent 请求直接运行仿真。")
            self.container.sim_runner.start_project(Path(self.current_project_meta.project_dir))

    def _refresh_history_panel(self, selected_record_id: int | None = None) -> None:
        if self.container is None:
            return

        project_dir = None
        if self.current_project_meta is not None:
            project_dir = self.current_project_meta.project_dir

        records = self.container.history_store.list_recent(project_dir=project_dir, limit=20)
        self.history_panel.set_records(records, selected_record_id=selected_record_id)

    def _ensure_project_built(self) -> bool:
        if self.container is None or self.current_project_meta is None:
            return False

        project_dir = Path(self.current_project_meta.project_dir)
        sumocfg_path = project_dir / "sumo" / "scenario.sumocfg"
        if sumocfg_path.exists():
            return True

        if self.current_project_context is not None and self.current_project_context.network and self.current_project_context.routes and self.current_project_context.simulation:
            self.append_log("当前项目缺少输出文件，按当前项目上下文重新构建。")
            result = self.container.project_builder.build_project(self.current_project_context)
            for file_path in result.generated_files:
                self.append_log(f"已生成文件：{file_path}")
            for issue in result.issues:
                self.append_log(f"{issue.level.upper()}: {issue.message}")
            return not any(issue.level == "error" for issue in result.issues)

        self.append_log("当前项目还没有 SUMO 文件，自动生成默认场景。")
        network_request = NetworkGenerationRequest(
            scenario_type=self.container.user_preferences.default_scenario_type,
            lane_count=2,
            road_length=200.0,
            speed_limit=13.89,
        )
        network = self.container.network_generator.generate(network_request)
        route_request = RouteGenerationRequest(
            flow_level=self.container.user_preferences.default_flow_level,
            duration_seconds=self.current_simulation_spec.end_time,
        )
        routes = self.container.route_generator.generate_routes(network, route_request)
        config_request = SimulationConfigRequest(
            duration_seconds=self.current_simulation_spec.end_time,
            step_length=self.current_simulation_spec.step_length,
            seed=self.current_simulation_spec.seed,
        )
        simulation = self.container.config_generator.build_simulation_spec(project_dir, config_request)
        self.current_project_context = ProjectContext(
            meta=self.current_project_meta,
            network=network,
            routes=routes,
            simulation=simulation,
            scenario_state=ProjectScenarioState(
                scenario_type=self.container.user_preferences.default_scenario_type,
                lane_count=2,
                road_length=200.0,
                speed_limit=13.89,
                flow_level=self.container.user_preferences.default_flow_level,
                duration_seconds=self.current_simulation_spec.end_time,
                step_length=self.current_simulation_spec.step_length,
                seed=self.current_simulation_spec.seed,
            ),
        )
        result = self.container.project_builder.build_project(self.current_project_context)

        for file_path in result.generated_files:
            self.append_log(f"已生成文件：{file_path}")
        for issue in result.issues:
            self.append_log(f"{issue.level.upper()}: {issue.message}")
        has_errors = any(issue.level == "error" for issue in result.issues)
        if has_errors:
            self.show_error("默认场景生成失败，请查看日志。")
            return False
        return True

    def _remember_recent_project(self, meta: ProjectMeta) -> None:
        if self.container is None:
            return
        item = RecentProjectItem(name=meta.name, project_dir=str(meta.project_dir), last_opened_at=datetime.now())
        self.container.recent_store.add_recent_project(item)
