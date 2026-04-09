
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from PySide6.QtCore import QObject, QThread, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QStatusBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from agent.image_models import ImageAnalysisResult, ImageAnalysisStatus, IntersectionImageDraft
from agent.orchestrator import AgentExecutionResult, AgentOrchestrator
from sumo_domain.project_spec import ProjectContext, ProjectMeta, ProjectScenarioState, RecentProjectItem
from sumo_domain.simulation_spec import SimulationSpec
from sumo_tools.config_generator import SimulationConfigRequest
from sumo_tools.network_generator import NetworkGenerationRequest
from sumo_tools.route_generator import RouteGenerationRequest
from sumo_tools.signal_logic import signal_additional_files
from ui.chat_panel import ChatPanel
from ui.control_panel import ControlPanel
from ui.history_panel import HistoryPanel
from ui.image_draft_dialog import ImageDraftDialog
from ui.project_dialog import NewProjectDialog
from ui.settings_dialog import SettingsDialog
from ui.signal_plan_panel import SignalPlanPanel
from ui.sim_status_panel import SimulationStatusPanel


class AgentTaskWorker(QObject):
    progressChanged = Signal(object)
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, runner: Callable[[Callable[[object], None]], object]) -> None:
        super().__init__()
        self._runner = runner

    def run(self) -> None:
        try:
            result = self._runner(self.progressChanged.emit)
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        self.succeeded.emit(result)


class MainWindow(QMainWindow):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.container = None
        self.current_project_meta: ProjectMeta | None = None
        self.current_project_context: ProjectContext | None = None
        self.current_simulation_spec = SimulationSpec()
        self.workspace_tabs: QTabWidget | None = None
        self._task_thread: QThread | None = None
        self._task_worker: AgentTaskWorker | None = None
        self._task_placeholder: QWidget | None = None
        self._task_kind: str | None = None
        self._close_after_task = False
        self._pending_image_draft: IntersectionImageDraft | None = None
        self._model_summary_label: QLabel | None = None
        self._streamed_reply_text = ""
        self._reply_stream_row: QWidget | None = None
        self._reply_stream_target_text = ""
        self._reply_stream_visible_text = ""
        self._reply_stream_index = 0
        self._reply_stream_complete = False
        self._reply_stream_timer = QTimer(self)
        self._reply_stream_timer.setInterval(34)
        self._reply_stream_timer.timeout.connect(self._advance_reply_stream)
        self.setWindowTitle("\u901a\u901a \u00b7 TrafficAgent")
        self.resize(1420, 860)
        self._build_ui()
        self._build_menu()

    def bind_services(self, container) -> None:
        self.container = container
        self.current_simulation_spec = SimulationSpec(end_time=container.user_preferences.default_duration)
        self.control_panel.load_simulation_spec(self.current_simulation_spec)
        self.container.sim_runner.stateChanged.connect(self.sim_status_panel.update_state)
        self.container.sim_runner.stateChanged.connect(self.signal_plan_panel.update_runtime_state)
        self.container.sim_runner.logProduced.connect(self.append_log)
        self.container.sim_runner.runFailed.connect(self.show_error)
        self.history_panel.clear_records()
        self._refresh_model_summary()
        self._sync_signal_panel()
        self.append_log("\u901a\u901a\u670d\u52a1\u5df2\u7ed1\u5b9a\u3002")
        self.statusBar().showMessage("\u901a\u901a\u5df2\u5c31\u7eea")

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._task_thread is not None and self._task_thread.isRunning():
            self._close_after_task = True
            self.statusBar().showMessage("\u6b63\u5728\u7b49\u5f85\u901a\u901a\u5b8c\u6210\u5f53\u524d\u4efb\u52a1\u540e\u518d\u5173\u95ed...")
            event.ignore()
            return
        super().closeEvent(event)

    def _build_ui(self) -> None:
        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(10)
        splitter.setObjectName("mainSplitter")

        self.chat_panel = ChatPanel()
        self.chat_panel.messageSubmitted.connect(self._handle_chat_message)
        self.chat_panel.imageSelected.connect(self._handle_image_selected)
        self.chat_panel.draftConfirmRequested.connect(self._handle_draft_confirm_requested)
        self.chat_panel.draftCustomizeRequested.connect(self._handle_draft_customize_requested)
        self.chat_panel.draftCancelRequested.connect(self._handle_draft_cancel_requested)
        self.chat_panel.draftReuploadRequested.connect(self._handle_draft_reupload_requested)

        right_panel = QWidget()
        right_panel.setObjectName("rightWorkspace")
        right_panel.setMinimumWidth(440)
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(12)

        self.control_panel = ControlPanel()
        self.control_panel.runRequested.connect(self._handle_run_requested)
        self.control_panel.pauseRequested.connect(self._handle_pause_requested)
        self.control_panel.resumeRequested.connect(self._handle_resume_requested)
        self.control_panel.stepRequested.connect(self._handle_step_requested)
        self.control_panel.stopRequested.connect(self._handle_stop_requested)
        self.control_panel.simulationParamsChanged.connect(self._handle_simulation_params_changed)

        self.signal_plan_panel = SignalPlanPanel()
        self.sim_status_panel = SimulationStatusPanel()
        self.history_panel = HistoryPanel()
        self.history_panel.refreshRequested.connect(self._refresh_history_panel)

        right_layout.addWidget(self._build_workspace_header())
        self.workspace_tabs = self._build_workspace_tabs()
        right_layout.addWidget(self.workspace_tabs, 1)

        splitter.addWidget(self.chat_panel)
        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 6)
        splitter.setStretchFactor(1, 5)

        wrapper = QWidget()
        wrapper.setObjectName("mainWrapper")
        wrapper_layout = QVBoxLayout(wrapper)
        wrapper_layout.setContentsMargins(12, 12, 12, 12)
        wrapper_layout.addWidget(splitter)
        self.setCentralWidget(wrapper)
        self.setStatusBar(QStatusBar())
        self._apply_window_style()

    def _build_workspace_tabs(self) -> QTabWidget:
        tabs = QTabWidget()
        tabs.setObjectName("workspaceTabs")
        tabs.setDocumentMode(True)
        tabs.setUsesScrollButtons(False)

        control_page = QWidget()
        control_layout = QVBoxLayout(control_page)
        control_layout.setContentsMargins(0, 6, 0, 0)
        control_layout.addWidget(self.control_panel)

        signal_page = QWidget()
        signal_layout = QVBoxLayout(signal_page)
        signal_layout.setContentsMargins(0, 6, 0, 0)
        signal_layout.addWidget(self.signal_plan_panel)

        status_page = QWidget()
        status_layout = QVBoxLayout(status_page)
        status_layout.setContentsMargins(0, 6, 0, 0)
        status_layout.addWidget(self.sim_status_panel)

        history_page = QWidget()
        history_layout = QVBoxLayout(history_page)
        history_layout.setContentsMargins(0, 6, 0, 0)
        history_layout.addWidget(self.history_panel)

        log_page = QWidget()
        log_layout = QVBoxLayout(log_page)
        log_layout.setContentsMargins(0, 6, 0, 0)
        log_layout.addWidget(self._build_log_card())

        tabs.addTab(control_page, "\u63a7\u5236")
        tabs.addTab(signal_page, "\u4fe1\u63a7")
        tabs.addTab(status_page, "\u72b6\u6001")
        tabs.addTab(history_page, "\u5386\u53f2")
        tabs.addTab(log_page, "\u65e5\u5fd7")
        return tabs

    def _build_menu(self) -> None:
        menu = self.menuBar()
        file_menu = menu.addMenu("\u6587\u4ef6")
        settings_menu = menu.addMenu("\u8bbe\u7f6e")
        view_menu = menu.addMenu("\u89c6\u56fe")

        new_project_action = QAction("\u65b0\u5efa\u9879\u76ee", self)
        new_project_action.triggered.connect(self._create_project)
        file_menu.addAction(new_project_action)

        settings_action = QAction("\u6a21\u578b\u4e0e\u504f\u597d\u8bbe\u7f6e", self)
        settings_action.triggered.connect(self._open_settings)
        settings_menu.addAction(settings_action)

        refresh_history_action = QAction("\u5237\u65b0\u64cd\u4f5c\u5386\u53f2", self)
        refresh_history_action.triggered.connect(self._refresh_history_panel)
        view_menu.addAction(refresh_history_action)

    def load_project(self, path: Path) -> None:
        if self.container is None:
            self.show_error("\u670d\u52a1\u5c1a\u672a\u521d\u59cb\u5316\uff0c\u6682\u65f6\u65e0\u6cd5\u52a0\u8f7d\u9879\u76ee\u3002")
            return
        try:
            meta = self.container.project_store.open_project(path)
        except FileNotFoundError as exc:
            self.show_error(str(exc))
            return
        self.current_project_meta = meta
        scenario_state = self.container.project_store.load_scenario_state(path)
        if scenario_state is not None:
            try:
                self.current_project_context = self._build_context_from_state(meta, scenario_state)
                self.current_simulation_spec = self.current_project_context.simulation or self.current_simulation_spec
                self.control_panel.load_simulation_spec(self.current_simulation_spec)
            except Exception as exc:
                self.append_log(f"\u52a0\u8f7d scenario_state \u5931\u8d25\uff1a{exc}")
                self.current_simulation_spec = self.current_simulation_spec.model_copy(update={"additional_files": []})
                self.control_panel.load_simulation_spec(self.current_simulation_spec)
                self.current_project_context = ProjectContext(meta=meta, simulation=self.current_simulation_spec)
        else:
            self.current_simulation_spec = self.current_simulation_spec.model_copy(update={"additional_files": []})
            self.control_panel.load_simulation_spec(self.current_simulation_spec)
            self.current_project_context = ProjectContext(meta=meta, simulation=self.current_simulation_spec)
        self._sync_signal_panel()
        self.append_log(f"\u5df2\u52a0\u8f7d\u9879\u76ee\uff1a{meta.name}")
        self.statusBar().showMessage(f"\u5f53\u524d\u9879\u76ee\uff1a{meta.name}")
        self._remember_recent_project(meta)
        self._refresh_history_panel()

    def refresh_project_view(self) -> None:
        if self.current_project_meta is None:
            self.statusBar().showMessage("\u5c1a\u672a\u6253\u5f00\u9879\u76ee")
            return
        self.statusBar().showMessage(f"\u5f53\u524d\u9879\u76ee\uff1a{self.current_project_meta.name}")

    def append_log(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_output.appendPlainText(f"[{timestamp}] {message}")

    def show_error(self, message: str) -> None:
        QMessageBox.critical(self, "\u9519\u8bef", message)
        self.append_log(f"\u9519\u8bef\uff1a{message}")

    def _create_project(self) -> None:
        if self.container is None:
            self.show_error("\u670d\u52a1\u5c1a\u672a\u521d\u59cb\u5316\uff0c\u6682\u65f6\u65e0\u6cd5\u521b\u5efa\u9879\u76ee\u3002")
            return
        dialog = NewProjectDialog(self.container.paths.projects_dir, self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        name = dialog.collect_project_name()
        base_dir = dialog.collect_project_path()
        if not name:
            self.show_error("\u9879\u76ee\u540d\u79f0\u4e0d\u80fd\u4e3a\u7a7a\u3002")
            return
        meta = self.container.project_store.create_project(name, base_dir)
        self.current_simulation_spec = self.current_simulation_spec.model_copy(update={"additional_files": []})
        self.control_panel.load_simulation_spec(self.current_simulation_spec)
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
        self.append_log(f"\u5df2\u521b\u5efa\u9879\u76ee\uff1a{meta.name}")
        self.statusBar().showMessage(f"\u5f53\u524d\u9879\u76ee\uff1a{meta.name}")
        self._sync_signal_panel()
        self._remember_recent_project(meta)
        self._refresh_history_panel()

    def _open_settings(self) -> None:
        if self.container is None:
            self.show_error("\u670d\u52a1\u5c1a\u672a\u521d\u59cb\u5316\uff0c\u6682\u65f6\u65e0\u6cd5\u6253\u5f00\u8bbe\u7f6e\u3002")
            return
        dialog = SettingsDialog(self)
        dialog.load_settings(self.container.model_config, self.container.user_preferences)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        self.container.model_config = dialog.collect_model_config()
        self.container.user_preferences = dialog.collect_user_preferences()
        self.container.config_store.save_model_config(self.container.model_config)
        self.container.config_store.save_user_preferences(self.container.user_preferences)
        if self.current_project_meta is None:
            self.current_simulation_spec = self.current_simulation_spec.model_copy(
                update={"end_time": self.container.user_preferences.default_duration}
            )
            self.control_panel.load_simulation_spec(self.current_simulation_spec)
        self._refresh_model_summary()
        self.statusBar().showMessage(f"\u6a21\u578b\u8bbe\u7f6e\u5df2\u4fdd\u5b58\uff1a{self.container.model_config.model}")
        self.append_log(f"\u5df2\u4fdd\u5b58\u6a21\u578b\u914d\u7f6e\u548c\u7528\u6237\u504f\u597d\uff0c\u5f53\u524d\u6a21\u578b\uff1a{self.container.model_config.model}")

    def _refresh_model_summary(self) -> None:
        if self._model_summary_label is None:
            return
        if self.container is None:
            self._model_summary_label.setText("\u5f53\u524d\u6a21\u578b\uff1a\u672a\u7ed1\u5b9a")
            return
        config = self.container.model_config
        key_state = "\u5df2\u914d\u7f6e Key" if config.api_key else "\u672a\u914d\u7f6e Key"
        vision_state = "\u652f\u6301\u8bc6\u56fe" if config.supports_vision else "\u6587\u672c\u6a21\u578b"
        self._model_summary_label.setText(f"\u5f53\u524d\u6a21\u578b\uff1a{config.model} | {key_state} | {vision_state}")

    def _handle_chat_message(self, text: str) -> None:
        if self.container is None:
            self.show_error("\u670d\u52a1\u5c1a\u672a\u521d\u59cb\u5316\u3002")
            return
        if self._task_thread is not None:
            self.statusBar().showMessage("\u901a\u901a\u6b63\u5728\u5904\u7406\u4e0a\u4e00\u6761\u4efb\u52a1\u3002")
            return
        orchestrator: AgentOrchestrator = self.container.agent_orchestrator
        if self._pending_image_draft is not None:
            if orchestrator.is_cancel_draft_text(text):
                self._cancel_pending_draft(announce=True)
                return
            if orchestrator.is_confirm_draft_text(text):
                self._start_agent_task(
                    kind="draft_materialize",
                    placeholder_text="\u901a\u901a\u6b63\u5728\u751f\u6210\u9879\u76ee...",
                    runner=lambda emit: orchestrator.materialize_image_draft(
                        self._pending_image_draft.model_copy(deep=True),
                        self._project_snapshot(),
                        progress_callback=emit,
                    ),
                )
                return
            self._start_agent_task(
                kind="draft_patch",
                placeholder_text="\u901a\u901a\u6b63\u5728\u7406\u89e3\u8349\u7a3f\u4fee\u6539...",
                runner=lambda emit: orchestrator.update_image_draft_from_text(
                    text,
                    self._pending_image_draft.model_copy(deep=True),
                    self._project_snapshot(),
                    progress_callback=emit,
                ),
            )
            return
        self._start_agent_task(
            kind="chat",
            placeholder_text="\u901a\u901a\u6b63\u5728\u7406\u89e3\u4f60\u7684\u9700\u6c42...",
            runner=lambda emit: orchestrator.handle_user_message(text, self._project_snapshot(), progress_callback=emit),
        )

    def _handle_image_selected(self, image_path: str) -> None:
        if self.container is None:
            self.show_error("\u670d\u52a1\u5c1a\u672a\u521d\u59cb\u5316\u3002")
            return
        if self._task_thread is not None:
            self.statusBar().showMessage("\u901a\u901a\u6b63\u5728\u5904\u7406\u4e0a\u4e00\u6761\u4efb\u52a1\u3002")
            return
        self.chat_panel.append_image_message(image_path)
        self._start_agent_task(
            kind="image_analysis",
            placeholder_text="\u901a\u901a\u6b63\u5728\u8bfb\u53d6\u56fe\u7247...",
            runner=lambda emit: self.container.agent_orchestrator.analyze_uploaded_image(
                image_path,
                self._project_snapshot(),
                progress_callback=emit,
            ),
        )

    def _handle_draft_confirm_requested(self) -> None:
        if self.container is None or self._pending_image_draft is None or self._task_thread is not None:
            return
        self._start_agent_task(
            kind="draft_materialize",
            placeholder_text="\u901a\u901a\u6b63\u5728\u6839\u636e\u8349\u7a3f\u751f\u6210\u9879\u76ee...",
            runner=lambda emit: self.container.agent_orchestrator.materialize_image_draft(
                self._pending_image_draft.model_copy(deep=True),
                self._project_snapshot(),
                progress_callback=emit,
            ),
        )

    def _handle_draft_customize_requested(self) -> None:
        if self._pending_image_draft is None:
            return
        dialog = ImageDraftDialog(self._pending_image_draft, self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        updated_draft = dialog.collect_draft(self._pending_image_draft.source_image_path)
        self._pending_image_draft = updated_draft
        result = ImageAnalysisResult(
            status=ImageAnalysisStatus.DRAFT_READY,
            reply_text="\u6211\u5df2\u7ecf\u6309\u4f60\u7684\u624b\u52a8\u8bbe\u7f6e\u66f4\u65b0\u4e86\u8fd9\u5f20\u8def\u53e3\u8349\u7a3f\u3002",
            draft=updated_draft,
            allow_confirm=updated_draft.can_confirm(),
            allow_customize=True,
            allow_reupload=True,
        )
        self.chat_panel.show_draft_preview(result)
        self.chat_panel.append_agent_message(result.reply_text)

    def _handle_draft_cancel_requested(self) -> None:
        self._cancel_pending_draft(announce=True)

    def _handle_draft_reupload_requested(self) -> None:
        self.chat_panel._choose_image()

    def _start_agent_task(
        self,
        kind: str,
        placeholder_text: str,
        runner: Callable[[Callable[[object], None]], object],
    ) -> None:
        if self._task_thread is not None:
            return
        self._stop_reply_stream(finalize=True)
        self._streamed_reply_text = ""
        self._task_kind = kind
        self._task_placeholder = self.chat_panel.append_status_message(placeholder_text)
        self.chat_panel.set_busy(True)
        self.statusBar().showMessage(placeholder_text)
        QApplication.processEvents()

        self._task_thread = QThread()
        self._task_worker = AgentTaskWorker(runner)
        self._task_worker.moveToThread(self._task_thread)
        self._task_thread.started.connect(self._task_worker.run)
        self._task_worker.progressChanged.connect(self._on_task_progress)
        self._task_worker.succeeded.connect(self._on_task_succeeded)
        self._task_worker.failed.connect(self._on_task_failed)
        self._task_worker.succeeded.connect(self._task_thread.quit)
        self._task_worker.failed.connect(self._task_thread.quit)
        self._task_thread.finished.connect(self._task_worker.deleteLater)
        self._task_thread.finished.connect(self._cleanup_task_worker)
        self._task_thread.finished.connect(self._task_thread.deleteLater)
        self._task_thread.start()

    def _on_task_progress(self, progress) -> None:
        if getattr(progress, "kind", "status") == "stream":
            self._append_stream_chunk(progress.message)
            self.statusBar().showMessage("\u901a\u901a\u6b63\u5728\u8f93\u51fa\u56de\u590d...")
            return
        if self._reply_stream_row is not None:
            self.statusBar().showMessage(progress.message)
            return
        if self._task_placeholder is not None:
            self._task_placeholder = self.chat_panel.update_message(self._task_placeholder, "status", progress.message)
        self.statusBar().showMessage(progress.message)

    def _on_task_succeeded(self, result: object) -> None:
        if isinstance(result, AgentExecutionResult):
            reply_text = result.reply_text.strip() if result.reply_text else "\u8bf7\u6c42\u5df2\u5904\u7406\uff0c\u4f46\u5f53\u524d\u6ca1\u6709\u8fd4\u56de\u8bf4\u660e\u3002"
            if self._streamed_reply_text:
                self._finish_streamed_reply(reply_text)
            elif self._task_placeholder is not None:
                self._begin_reply_stream(reply_text, self._task_placeholder)
                self._task_placeholder = None
            else:
                self._begin_reply_stream(reply_text)
            if self._task_kind == "draft_materialize":
                self._cancel_pending_draft(announce=False)
            self._apply_agent_result(result)
            self.statusBar().showMessage(f"{result.assistant_name} \u5df2\u5b8c\u6210\u672c\u8f6e\u5904\u7406")
        elif isinstance(result, ImageAnalysisResult):
            if self._task_placeholder is not None:
                self._task_placeholder = self.chat_panel.replace_message(self._task_placeholder, "assistant", result.reply_text)
                self._task_placeholder = None
            else:
                self.chat_panel.append_agent_message(result.reply_text)
            self._pending_image_draft = result.draft
            self.chat_panel.show_draft_preview(result)
            self.statusBar().showMessage("\u56fe\u7247\u8bc6\u522b\u5df2\u5b8c\u6210")
        else:
            if self._task_placeholder is not None:
                self._task_placeholder = self.chat_panel.replace_message(self._task_placeholder, "assistant", str(result))
                self._task_placeholder = None
        self.chat_panel.set_busy(False)

    def _on_task_failed(self, error_message: str) -> None:
        self._stop_reply_stream(finalize=True)
        self._streamed_reply_text = ""
        message = f"\u5904\u7406\u4efb\u52a1\u65f6\u51fa\u9519\uff1a{error_message}"
        if self._task_placeholder is not None:
            self._task_placeholder = self.chat_panel.replace_message(self._task_placeholder, "assistant", message)
            self._task_placeholder = None
        else:
            self.chat_panel.append_agent_message(message)
        self.append_log(f"\u540e\u53f0\u4efb\u52a1\u5f02\u5e38\uff1a{error_message}")
        self.chat_panel.set_busy(False)
        self.statusBar().showMessage("\u901a\u901a\u5904\u7406\u5931\u8d25")

    def _append_stream_chunk(self, chunk: str) -> None:
        if not chunk:
            return
        if self._reply_stream_row is None:
            if self._task_placeholder is None:
                self._reply_stream_row = self.chat_panel.append_agent_message("", render_markdown=False)
            else:
                self._reply_stream_row = self.chat_panel.replace_message(
                    self._task_placeholder,
                    "assistant",
                    "",
                    render_markdown=False,
                )
                self._task_placeholder = None
            self._reply_stream_visible_text = ""
            self._reply_stream_index = 0
        self._streamed_reply_text += chunk
        self._reply_stream_target_text += chunk
        self._reply_stream_complete = False
        if not self._reply_stream_timer.isActive():
            self._reply_stream_timer.start()

    def _finish_streamed_reply(self, final_text: str) -> None:
        final_message = final_text or self._streamed_reply_text
        if self._reply_stream_row is None:
            self.chat_panel.append_agent_message(final_message)
            self._task_placeholder = None
            self._streamed_reply_text = ""
            return
        self._reply_stream_target_text = final_message
        self._reply_stream_complete = True
        if self._reply_stream_index >= len(self._reply_stream_target_text):
            self._stop_reply_stream(finalize=True)
        elif not self._reply_stream_timer.isActive():
            self._reply_stream_timer.start()
        self._streamed_reply_text = ""
        self._task_placeholder = None

    def _begin_reply_stream(self, text: str, row_widget: QWidget | None = None) -> None:
        self._stop_reply_stream(finalize=True)
        self._streamed_reply_text = ""
        if row_widget is None:
            row_widget = self.chat_panel.append_agent_message("", render_markdown=False)
        else:
            row_widget = self.chat_panel.replace_message(
                row_widget,
                "assistant",
                "",
                render_markdown=False,
            )
        self._reply_stream_row = row_widget
        self._reply_stream_target_text = text or "\u8bf7\u6c42\u5df2\u5904\u7406\u3002"
        self._reply_stream_visible_text = ""
        self._reply_stream_index = 0
        self._reply_stream_complete = True
        if not self._reply_stream_timer.isActive():
            self._reply_stream_timer.start()

    def _advance_reply_stream(self) -> None:
        if self._reply_stream_row is None:
            self._reply_stream_timer.stop()
            return
        if self._reply_stream_index >= len(self._reply_stream_target_text):
            if self._reply_stream_complete:
                self._stop_reply_stream(finalize=True)
            else:
                self._reply_stream_timer.stop()
            return
        next_index = min(
            len(self._reply_stream_target_text),
            self._reply_stream_index + self._reply_stream_step_size(),
        )
        self._reply_stream_index = next_index
        self._reply_stream_visible_text = self._reply_stream_target_text[: self._reply_stream_index]
        self._reply_stream_row = self.chat_panel.update_message(
            self._reply_stream_row,
            "assistant",
            self._reply_stream_visible_text,
            render_markdown=False,
            relayout=False,
        )
        if self._reply_stream_index >= len(self._reply_stream_target_text) and self._reply_stream_complete:
            self._stop_reply_stream(finalize=True)

    def _reply_stream_step_size(self) -> int:
        backlog = len(self._reply_stream_target_text) - self._reply_stream_index
        if backlog > 320:
            return 4
        if backlog > 120:
            return 3
        return 2

    def _stop_reply_stream(self, finalize: bool) -> None:
        if self._reply_stream_timer.isActive():
            self._reply_stream_timer.stop()
        if finalize and self._reply_stream_row is not None:
            final_text = self._reply_stream_target_text or self._reply_stream_visible_text
            finalized_row = self.chat_panel.replace_message(
                self._reply_stream_row,
                "assistant",
                final_text,
                render_markdown=True,
            )
            if self._task_placeholder is self._reply_stream_row:
                self._task_placeholder = finalized_row
            self._reply_stream_row = finalized_row
        self._reply_stream_row = None
        self._reply_stream_target_text = ""
        self._reply_stream_visible_text = ""
        self._reply_stream_index = 0
        self._reply_stream_complete = False

    def _cleanup_task_worker(self) -> None:
        self._task_worker = None
        self._task_thread = None
        self._task_kind = None
        if self._close_after_task:
            self._close_after_task = False
            self.close()

    def _cancel_pending_draft(self, announce: bool) -> None:
        self._pending_image_draft = None
        self.chat_panel.clear_draft_preview()
        if announce:
            self.chat_panel.append_agent_message("\u5df2\u53d6\u6d88\u5f53\u524d\u56fe\u7247\u8349\u7a3f\u3002\u4f60\u53ef\u4ee5\u7ee7\u7eed\u804a\u5929\uff0c\u6216\u8005\u91cd\u65b0\u4e0a\u4f20\u4e00\u5f20\u56fe\u7247\u3002")

    def _project_snapshot(self) -> ProjectContext | None:
        return self.current_project_context.model_copy(deep=True) if self.current_project_context is not None else None

    def _apply_agent_result(self, result: AgentExecutionResult) -> None:
        if result.updated_project is not None:
            self.current_project_context = result.updated_project
            self.current_project_meta = result.updated_project.meta
            self.current_simulation_spec = result.updated_project.simulation or self.current_simulation_spec
            self.control_panel.load_simulation_spec(self.current_simulation_spec)
            self._sync_signal_panel()
            self.statusBar().showMessage(f"\u5f53\u524d\u9879\u76ee\uff1a{self.current_project_meta.name}")
            self._remember_recent_project(self.current_project_meta)
        if result.operation_summary:
            self.append_log(f"\u53d8\u66f4\u786e\u8ba4\uff1a{result.operation_summary.replace(chr(10), ' | ')}")
        if result.history_record_id is not None:
            self.append_log(f"\u5df2\u5199\u5165\u64cd\u4f5c\u5386\u53f2\uff1a#{result.history_record_id}")
        for file_path in result.generated_files:
            self.append_log(f"\u5df2\u751f\u6210\u6587\u4ef6\uff1a{file_path}")
        for issue in result.issues:
            self.append_log(issue)
        self._refresh_history_panel(result.history_record_id)
        if result.should_run_simulation:
            if self.current_project_meta is None:
                self.show_error("\u5f53\u524d\u6ca1\u6709\u53ef\u8fd0\u884c\u7684\u9879\u76ee\u3002")
                return
            if not self._ensure_project_built():
                return
            if self.workspace_tabs is not None:
                self.workspace_tabs.setCurrentIndex(2)
            self.append_log("Agent \u8bf7\u6c42\u76f4\u63a5\u8fd0\u884c\u4eff\u771f\u3002")
            self.container.sim_runner.start_project(Path(self.current_project_meta.project_dir))
        elif result.history_record_id is not None and self.workspace_tabs is not None:
            self.workspace_tabs.setCurrentIndex(3)

    def _handle_run_requested(self) -> None:
        if self.container is None:
            self.show_error("\u670d\u52a1\u5c1a\u672a\u521d\u59cb\u5316\u3002")
            return
        if self.current_project_meta is None:
            self._create_implicit_project_for_run()
        if self.current_project_meta is None:
            self.show_error("\u65e0\u6cd5\u521b\u5efa\u8fd0\u884c\u9879\u76ee\u3002")
            return
        if not self._ensure_project_built():
            return
        if self.workspace_tabs is not None:
            self.workspace_tabs.setCurrentIndex(2)
        self.append_log("\u6536\u5230\u8fd0\u884c\u8bf7\u6c42\uff0c\u51c6\u5907\u901a\u8fc7 TraCI \u542f\u52a8 SUMO\u3002")
        self.container.sim_runner.start_project(Path(self.current_project_meta.project_dir))

    def _handle_pause_requested(self) -> None:
        if self.container is not None:
            self.container.sim_runner.pause()

    def _handle_resume_requested(self) -> None:
        if self.container is not None:
            self.container.sim_runner.resume()

    def _handle_step_requested(self) -> None:
        if self.container is not None:
            self.container.sim_runner.step_once()

    def _handle_stop_requested(self) -> None:
        if self.container is not None:
            self.container.sim_runner.stop()

    def _handle_simulation_params_changed(self, spec: SimulationSpec) -> None:
        spec = spec.model_copy(update={"additional_files": list(self.current_simulation_spec.additional_files)})
        self.current_simulation_spec = spec
        if self.current_project_context is not None:
            scenario_state = self.current_project_context.scenario_state
            if scenario_state is not None:
                scenario_state = scenario_state.model_copy(update={"duration_seconds": spec.end_time, "step_length": spec.step_length, "seed": spec.seed})
                if self.current_project_meta is not None and self.container is not None:
                    self.container.project_store.save_scenario_state(Path(self.current_project_meta.project_dir), scenario_state)
            self.current_project_context = self.current_project_context.model_copy(update={"simulation": spec, "scenario_state": scenario_state})
        self._sync_signal_panel()
        self.append_log(f"\u53c2\u6570\u5df2\u66f4\u65b0\uff1a\u65f6\u957f={spec.end_time}s, \u6b65\u957f={spec.step_length}, seed={spec.seed}")

    def _create_implicit_project_for_run(self) -> None:
        if self.container is None:
            return
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        meta = self.container.project_store.create_project(f"quick_run_{timestamp}")
        self.current_simulation_spec = self.current_simulation_spec.model_copy(update={"additional_files": []})
        self.control_panel.load_simulation_spec(self.current_simulation_spec)
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
        self.statusBar().showMessage(f"\u5f53\u524d\u9879\u76ee\uff1a{meta.name}")
        self._sync_signal_panel()
        self._remember_recent_project(meta)
        self._refresh_history_panel()
        self.append_log(f"\u672a\u68c0\u6d4b\u5230\u5f53\u524d\u9879\u76ee\uff0c\u5df2\u81ea\u52a8\u521b\u5efa\u4e34\u65f6\u9879\u76ee\uff1a{meta.name}")

    def _refresh_history_panel(self, selected_record_id: int | None = None) -> None:
        if self.container is None:
            return
        project_dir = self.current_project_meta.project_dir if self.current_project_meta is not None else None
        records = self.container.history_store.list_recent(project_dir=project_dir, limit=20)
        self.history_panel.set_records(records, selected_record_id=selected_record_id)

    def _ensure_project_built(self) -> bool:
        if self.container is None or self.current_project_meta is None:
            return False
        project_dir = Path(self.current_project_meta.project_dir)
        validation_issues = self.container.validator.validate_project(project_dir)
        has_validation_errors = any(issue.level == "error" for issue in validation_issues)
        sumocfg_path = project_dir / "sumo" / "scenario.sumocfg"
        if sumocfg_path.exists() and not has_validation_errors:
            self._log_validation_issues(validation_issues, prefix="\u8fd0\u884c\u524d\u6821\u9a8c")
            return True
        if validation_issues:
            self.append_log("\u5f53\u524d\u9879\u76ee\u8f93\u51fa\u4e0d\u5b8c\u6574\u6216\u4e0d\u53ef\u8fd0\u884c\uff0c\u51c6\u5907\u91cd\u5efa\u3002")
            self._log_validation_issues(validation_issues, prefix="\u8fd0\u884c\u524d\u6821\u9a8c")
        if self.current_project_context is not None and self.current_project_context.network and self.current_project_context.routes and self.current_project_context.simulation:
            self.append_log("\u6309\u5f53\u524d\u9879\u76ee\u4e0a\u4e0b\u6587\u91cd\u65b0\u6784\u5efa SUMO \u6587\u4ef6\u3002")
            result = self.container.project_builder.build_project(self.current_project_context)
            for file_path in result.generated_files:
                self.append_log(f"\u5df2\u751f\u6210\u6587\u4ef6\uff1a{file_path}")
            self._log_validation_issues(result.issues, prefix="\u6784\u5efa\u7ed3\u679c")
            final_issues = self.container.validator.validate_project(project_dir)
            self._log_validation_issues(final_issues, prefix="\u91cd\u5efa\u540e\u6821\u9a8c")
            if any(issue.level == "error" for issue in final_issues):
                self.show_error("\u5f53\u524d\u9879\u76ee\u91cd\u5efa\u5931\u8d25\uff0c\u8bf7\u67e5\u770b\u65e5\u5fd7\u3002")
                return False
            return True
        existing_sumo_files = [item.name for item in (project_dir / "sumo").glob("*") if item.is_file()]
        if existing_sumo_files:
            self.append_log("\u68c0\u6d4b\u5230\u5f53\u524d\u9879\u76ee\u5b58\u5728\u6b8b\u7f3a\u7684 SUMO \u6587\u4ef6\uff0c\u4f46\u6ca1\u6709\u53ef\u6062\u590d\u7684\u5b8c\u6574\u4e0a\u4e0b\u6587\uff0c\u5df2\u963b\u6b62\u81ea\u52a8\u8986\u76d6\u3002")
            self.append_log(f"\u6b8b\u7f3a\u6587\u4ef6\uff1a{', '.join(existing_sumo_files)}")
            self.show_error("\u5f53\u524d\u9879\u76ee\u6587\u4ef6\u4e0d\u5b8c\u6574\uff0c\u4e14\u7f3a\u5c11\u53ef\u6062\u590d\u7684\u9879\u76ee\u4e0a\u4e0b\u6587\u3002\u8bf7\u901a\u8fc7\u804a\u5929\u91cd\u65b0\u751f\u6210\u573a\u666f\uff0c\u6216\u65b0\u5efa\u9879\u76ee\u3002")
            return False
        self.append_log("\u5f53\u524d\u9879\u76ee\u8fd8\u6ca1\u6709\u53ef\u7528 SUMO \u6587\u4ef6\uff0c\u81ea\u52a8\u751f\u6210\u9ed8\u8ba4\u573a\u666f\u3002")
        network_request = NetworkGenerationRequest(
            scenario_type=self.container.user_preferences.default_scenario_type,
            lane_count=2,
            road_length=200.0,
            speed_limit=13.89,
        )
        network = self.container.network_generator.generate(network_request)
        route_request = RouteGenerationRequest(flow_level=self.container.user_preferences.default_flow_level, duration_seconds=self.current_simulation_spec.end_time)
        routes = self.container.route_generator.generate_routes(network, route_request)
        config_request = SimulationConfigRequest(duration_seconds=self.current_simulation_spec.end_time, step_length=self.current_simulation_spec.step_length, seed=self.current_simulation_spec.seed)
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
            self.append_log(f"\u5df2\u751f\u6210\u6587\u4ef6\uff1a{file_path}")
        self._log_validation_issues(result.issues, prefix="\u6784\u5efa\u7ed3\u679c")
        final_issues = self.container.validator.validate_project(project_dir)
        self._log_validation_issues(final_issues, prefix="\u91cd\u5efa\u540e\u6821\u9a8c")
        if any(issue.level == "error" for issue in final_issues):
            self.show_error("\u9ed8\u8ba4\u573a\u666f\u751f\u6210\u5931\u8d25\uff0c\u8bf7\u67e5\u770b\u65e5\u5fd7\u3002")
            return False
        return True

    def _log_validation_issues(self, issues, prefix: str) -> None:
        for issue in issues:
            location = f" ({issue.file})" if getattr(issue, "file", None) else ""
            self.append_log(f"{prefix} {issue.level.upper()}: {issue.message}{location}")

    def _remember_recent_project(self, meta: ProjectMeta) -> None:
        if self.container is None:
            return
        item = RecentProjectItem(name=meta.name, project_dir=str(meta.project_dir), last_opened_at=datetime.now())
        self.container.recent_store.add_recent_project(item)

    def _build_context_from_state(self, meta: ProjectMeta, state: ProjectScenarioState) -> ProjectContext:
        if self.container is None:
            return ProjectContext(meta=meta, scenario_state=state)
        signal_enabled = state.signal_plan is not None and state.signal_plan.enabled
        network = self.container.network_generator.generate(
            NetworkGenerationRequest(
                scenario_type=state.scenario_type,
                lane_count=state.lane_count,
                directional_lanes=state.directional_lanes,
                road_length=state.road_length,
                speed_limit=state.speed_limit,
                signal_enabled=signal_enabled,
            )
        )
        routes = self.container.route_generator.generate_routes(
            network,
            RouteGenerationRequest(
                flow_level=state.flow_level,
                flow_rate=state.flow_rate,
                duration_seconds=state.duration_seconds,
                traffic_bias=state.traffic_bias,
            ),
        )
        simulation = self.container.config_generator.build_simulation_spec(
            Path(meta.project_dir),
            SimulationConfigRequest(
                duration_seconds=state.duration_seconds,
                step_length=state.step_length,
                seed=state.seed,
                additional_files=signal_additional_files(state.signal_plan),
            ),
        )
        return ProjectContext(meta=meta, network=network, routes=routes, simulation=simulation, scenario_state=state)

    def _sync_signal_panel(self) -> None:
        self.signal_plan_panel.load_project(self.current_project_context)

    def _build_workspace_header(self) -> QFrame:
        card = QFrame()
        card.setObjectName("workspaceHero")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(8)

        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(12)

        title_layout = QVBoxLayout()
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(6)

        eyebrow = QLabel("CONTROL ROOM")
        eyebrow.setObjectName("workspaceEyebrow")
        title = QLabel("\u53f3\u4fa7\u5de5\u4f5c\u53f0")
        title.setObjectName("workspaceTitle")
        description = QLabel("\u53c2\u6570\u3001\u72b6\u6001\u3001\u5386\u53f2\u548c\u65e5\u5fd7\u5df2\u7ecf\u5207\u6362\u4e3a\u6807\u7b7e\u5de5\u4f5c\u533a\uff0c\u907f\u514d\u5c0f\u5c4f\u6216\u72ed\u5bbd\u5e03\u5c40\u4e0b\u5404\u4e2a\u6a21\u5757\u4e92\u76f8\u6324\u538b\u3002")
        description.setObjectName("workspaceDescription")
        description.setWordWrap(True)
        self._model_summary_label = QLabel("\u5f53\u524d\u6a21\u578b\uff1a\u672a\u7ed1\u5b9a")
        self._model_summary_label.setObjectName("workspaceMeta")
        self._model_summary_label.setWordWrap(True)

        settings_button = QPushButton("\u6a21\u578b\u8bbe\u7f6e")
        settings_button.setObjectName("heroAction")
        settings_button.clicked.connect(self._open_settings)

        title_layout.addWidget(eyebrow)
        title_layout.addWidget(title)
        top_row.addLayout(title_layout, 1)
        top_row.addWidget(settings_button, 0, Qt.AlignTop)

        layout.addLayout(top_row)
        layout.addWidget(description)
        layout.addWidget(self._model_summary_label)
        return card

    def _build_log_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("workspaceCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)
        title = QLabel("\u6267\u884c\u65e5\u5fd7")
        title.setObjectName("workspaceCardTitle")
        hint = QLabel("\u8fd9\u91cc\u4fdd\u7559\u5de5\u5177\u6267\u884c\u3001\u6784\u5efa\u6821\u9a8c\u548c\u4eff\u771f\u8fd0\u884c\u7684\u65f6\u95f4\u7ebf\uff0c\u65b9\u4fbf\u5feb\u901f\u5b9a\u4f4d\u95ee\u9898\u3002")
        hint.setObjectName("workspaceCardHint")
        hint.setWordWrap(True)
        self.log_output = QPlainTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setPlaceholderText("\u8fd9\u91cc\u4f1a\u663e\u793a\u901a\u901a\u7684\u6267\u884c\u65f6\u95f4\u7ebf\u3001\u9879\u76ee\u6784\u5efa\u8bb0\u5f55\u548c\u540e\u7eed\u4eff\u771f\u8f93\u51fa\u3002")
        self.log_output.setObjectName("logOutput")
        layout.addWidget(title)
        layout.addWidget(hint)
        layout.addWidget(self.log_output, 1)
        return card

    def _apply_window_style(self) -> None:
        self.setStyleSheet(
            """
            QWidget#mainWrapper { background: #F5F7FB; }
            QWidget#rightWorkspace { background: transparent; }
            QFrame#workspaceHero { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #F8FBFF, stop:1 #F1F5FF); border: 1px solid #E1E7F0; border-radius: 18px; }
            QFrame#workspaceCard { background: #FBFCFE; border: 1px solid #E7EDF5; border-radius: 18px; }
            QTabWidget#workspaceTabs::pane { border: 1px solid #E4EAF3; border-radius: 18px; background: #FBFCFE; top: -1px; }
            QTabWidget#workspaceTabs QWidget { background: transparent; }
            QTabBar::tab { background: #EEF3F9; color: #475569; border: 1px solid transparent; border-radius: 12px; padding: 10px 16px; margin-right: 6px; min-width: 64px; font-weight: 600; }
            QTabBar::tab:selected { background: #FFFFFF; color: #0F172A; border-color: #D8E2F0; }
            QLabel#workspaceEyebrow { color: #64748B; font-size: 11px; font-weight: 700; letter-spacing: 0.08em; }
            QLabel#workspaceTitle, QLabel#workspaceCardTitle { color: #0F172A; font-size: 16px; font-weight: 600; }
            QLabel#workspaceDescription, QLabel#workspaceCardHint { color: #475569; font-size: 12px; }
            QLabel#workspaceMeta { color: #334155; font-size: 12px; font-weight: 600; }
            QPushButton#heroAction { background: #FFFFFF; color: #0F172A; border: 1px solid #D8E2F0; border-radius: 12px; padding: 9px 14px; font-weight: 600; }
            QPushButton#heroAction:hover { background: #F8FAFC; border-color: #B7C5D9; }
            QPlainTextEdit#logOutput { background: #FFFFFF; border: 1px solid #E3EAF4; border-radius: 14px; color: #0F172A; padding: 12px; selection-background-color: #DCE9FF; }
            QStatusBar { background: #F8FAFC; border-top: 1px solid #E7EDF5; color: #475569; }
            QSplitter#mainSplitter::handle { background: transparent; }
            QSplitter#mainSplitter::handle:hover { background: #E2E8F0; border-radius: 3px; margin: 8px 0; }
            """
        )
