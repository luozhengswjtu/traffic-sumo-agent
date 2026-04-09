from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView, QFrame, QGridLayout, QLabel, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

from sumo_domain.project_spec import ProjectContext
from sumo_domain.signal_plan import SignalPlanSpec
from sumo_domain.simulation_spec import SimulationRuntimeState
from sumo_tools.signal_logic import build_signal_phase_preview


class SignalPlanPanel(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._current_runtime = None
        self._build_ui()
        self.load_project(None)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        card = QFrame()
        card.setObjectName("signalCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(18, 18, 18, 18)
        card_layout.setSpacing(14)

        title = QLabel("\u4fe1\u63a7\u65b9\u6848")
        title.setObjectName("panelTitle")
        hint = QLabel("\u9996\u7248\u8bf7\u901a\u8fc7\u804a\u5929\u4fee\u6539\u4fe1\u63a7\u53c2\u6570\uff0c\u53f3\u4fa7\u4ec5\u5c55\u793a\u5f53\u524d\u65b9\u6848\u548c\u8fd0\u884c\u6001\u3002")
        hint.setObjectName("panelHint")
        hint.setWordWrap(True)

        summary_grid = QGridLayout()
        summary_grid.setHorizontalSpacing(10)
        summary_grid.setVerticalSpacing(10)
        self.enabled_value = self._create_metric_card(summary_grid, 0, 0, "\u662f\u5426\u542f\u7528", "-")
        self.plan_value = self._create_metric_card(summary_grid, 0, 1, "\u65b9\u6848", "-")
        self.cycle_value = self._create_metric_card(summary_grid, 0, 2, "\u5468\u671f", "-")
        self.offset_value = self._create_metric_card(summary_grid, 1, 0, "Offset", "-")
        self.yellow_value = self._create_metric_card(summary_grid, 1, 1, "\u9ec4\u706f", "-")
        self.all_red_value = self._create_metric_card(summary_grid, 1, 2, "\u5168\u7ea2", "-")
        self.ns_green_value = self._create_metric_card(summary_grid, 2, 0, "\u5357\u5317\u7eff", "-")
        self.ew_green_value = self._create_metric_card(summary_grid, 2, 1, "\u4e1c\u897f\u7eff", "-")
        self.runtime_phase_value = self._create_metric_card(summary_grid, 2, 2, "\u5f53\u524d\u76f8\u4f4d", "-")

        runtime_panel = QFrame()
        runtime_panel.setObjectName("surfacePanel")
        runtime_layout = QVBoxLayout(runtime_panel)
        runtime_layout.setContentsMargins(14, 14, 14, 14)
        runtime_layout.setSpacing(8)
        runtime_title = QLabel("\u8fd0\u884c\u6001")
        runtime_title.setObjectName("sectionLabel")
        self.runtime_value = QLabel("\u5c1a\u672a\u5f00\u59cb\u4eff\u771f")
        self.runtime_value.setObjectName("messageValue")
        self.runtime_value.setWordWrap(True)
        runtime_layout.addWidget(runtime_title)
        runtime_layout.addWidget(self.runtime_value)

        self.phase_table = QTableWidget(0, 3)
        self.phase_table.setHorizontalHeaderLabels(["\u76f8\u4f4d", "\u65f6\u957f(s)", "\u7c7b\u578b"])
        self.phase_table.horizontalHeader().setStretchLastSection(True)
        self.phase_table.verticalHeader().setVisible(False)
        self.phase_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.phase_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.phase_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.phase_table.setAlternatingRowColors(True)

        card_layout.addWidget(title)
        card_layout.addWidget(hint)
        card_layout.addLayout(summary_grid)
        card_layout.addWidget(runtime_panel)
        card_layout.addWidget(self.phase_table)
        layout.addWidget(card)

        self.setStyleSheet(
            """
            QFrame#signalCard {
                background: #F8FAFC;
                border: 1px solid #E2E8F0;
                border-radius: 18px;
            }
            QFrame#surfacePanel,
            QFrame#metricCard {
                background: #FFFFFF;
                border: 1px solid #E2E8F0;
                border-radius: 14px;
            }
            QLabel#panelTitle {
                color: #0F172A;
                font-size: 15px;
                font-weight: 600;
            }
            QLabel#panelHint {
                color: #64748B;
                font-size: 12px;
            }
            QLabel#sectionLabel,
            QLabel#metricLabel {
                color: #475569;
                font-size: 12px;
                font-weight: 600;
            }
            QLabel#metricValue {
                color: #0F172A;
                font-size: 17px;
                font-weight: 600;
            }
            QLabel#messageValue {
                color: #0F172A;
                font-size: 13px;
            }
            QTableWidget {
                background: #FFFFFF;
                border: 1px solid #E2E8F0;
                border-radius: 14px;
                gridline-color: #E2E8F0;
            }
            QHeaderView::section {
                background: #F8FAFC;
                color: #475569;
                border: none;
                border-bottom: 1px solid #E2E8F0;
                padding: 8px;
                font-weight: 600;
            }
            """
        )

    def load_project(self, project: ProjectContext | None) -> None:
        signal_plan = project.scenario_state.signal_plan if project and project.scenario_state else None
        self._apply_signal_plan(signal_plan)
        self._apply_runtime(self._current_runtime)

    def update_runtime_state(self, state: SimulationRuntimeState) -> None:
        self._current_runtime = state.signal_status
        self._apply_runtime(state.signal_status)

    def _apply_signal_plan(self, signal_plan: SignalPlanSpec | None) -> None:
        if signal_plan is None or not signal_plan.enabled:
            for label in (
                self.enabled_value,
                self.plan_value,
                self.cycle_value,
                self.offset_value,
                self.yellow_value,
                self.all_red_value,
                self.ns_green_value,
                self.ew_green_value,
            ):
                label.setText("-")
            self.enabled_value.setText("\u5426")
            self.phase_table.setRowCount(0)
            return

        self.enabled_value.setText("\u662f")
        self.plan_value.setText(signal_plan.plan_name)
        self.cycle_value.setText(str(signal_plan.cycle_seconds))
        self.offset_value.setText(str(signal_plan.offset_seconds))
        self.yellow_value.setText(str(signal_plan.yellow_seconds))
        self.all_red_value.setText(str(signal_plan.all_red_seconds))
        self.ns_green_value.setText(str(signal_plan.ns_green_seconds))
        self.ew_green_value.setText(str(signal_plan.ew_green_seconds))

        preview = build_signal_phase_preview(signal_plan)
        self.phase_table.setRowCount(len(preview))
        for row, phase in enumerate(preview):
            self.phase_table.setItem(row, 0, QTableWidgetItem(phase.name))
            self.phase_table.setItem(row, 1, QTableWidgetItem(str(phase.duration_seconds)))
            self.phase_table.setItem(row, 2, QTableWidgetItem(phase.state_kind))

    def _apply_runtime(self, runtime) -> None:
        if runtime is None:
            self.runtime_phase_value.setText("-")
            self.runtime_value.setText("\u5c1a\u672a\u5f00\u59cb\u4eff\u771f")
            return
        self.runtime_phase_value.setText(runtime.phase_name or str(runtime.phase_index))
        self.runtime_value.setText(
            f"TLS={runtime.tls_id} | program={runtime.program_id} | phase={runtime.phase_index} | nextSwitch={runtime.next_switch_time:.1f}"
        )

    def _create_metric_card(self, grid: QGridLayout, row: int, column: int, title: str, value: str) -> QLabel:
        card = QFrame()
        card.setObjectName("metricCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)

        title_label = QLabel(title)
        title_label.setObjectName("metricLabel")
        value_label = QLabel(value)
        value_label.setObjectName("metricValue")

        layout.addWidget(title_label)
        layout.addWidget(value_label)
        grid.addWidget(card, row, column)
        return value_label
