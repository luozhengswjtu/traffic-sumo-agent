from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from sumo_domain.simulation_spec import SimulationRuntimeState


class SimulationStatusPanel(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._build_ui()
        self.reset()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        card = QFrame()
        card.setObjectName("statusCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(18, 18, 18, 18)
        card_layout.setSpacing(14)

        title = QLabel("仿真状态")
        title.setObjectName("panelTitle")
        hint = QLabel("右侧状态信息保持可读和紧凑，但避免默认表单式堆叠。")
        hint.setObjectName("panelHint")
        hint.setWordWrap(True)

        top_row = QHBoxLayout()
        top_row.setSpacing(10)

        status_panel = QFrame()
        status_panel.setObjectName("surfacePanel")
        status_layout = QVBoxLayout(status_panel)
        status_layout.setContentsMargins(14, 14, 14, 14)
        status_layout.setSpacing(10)
        status_title = QLabel("当前状态")
        status_title.setObjectName("sectionLabel")
        self.status_value = QLabel("idle")
        self.status_value.setAlignment(Qt.AlignCenter)
        self.status_value.setObjectName("statusBadge")
        status_layout.addWidget(status_title)
        status_layout.addWidget(self.status_value)

        message_panel = QFrame()
        message_panel.setObjectName("surfacePanel")
        message_layout = QVBoxLayout(message_panel)
        message_layout.setContentsMargins(14, 14, 14, 14)
        message_layout.setSpacing(8)
        message_title = QLabel("运行说明")
        message_title.setObjectName("sectionLabel")
        self.message_value = QLabel("尚未开始仿真")
        self.message_value.setObjectName("messageValue")
        self.message_value.setWordWrap(True)
        message_layout.addWidget(message_title)
        message_layout.addWidget(self.message_value)

        top_row.addWidget(status_panel, 1)
        top_row.addWidget(message_panel, 2)

        stats_grid = QGridLayout()
        stats_grid.setHorizontalSpacing(10)
        stats_grid.setVerticalSpacing(10)
        self.time_value = self._create_metric_card(stats_grid, 0, 0, "仿真时间", "0.0")
        self.vehicle_value = self._create_metric_card(stats_grid, 0, 1, "车辆数", "0")
        self.speed_value = self._create_metric_card(stats_grid, 0, 2, "平均速度", "-")

        card_layout.addWidget(title)
        card_layout.addWidget(hint)
        card_layout.addLayout(top_row)
        card_layout.addLayout(stats_grid)
        layout.addWidget(card)

        self.setStyleSheet(
            """
            QFrame#statusCard {
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
                font-size: 18px;
                font-weight: 600;
            }
            QLabel#messageValue {
                color: #0F172A;
                font-size: 13px;
            }
            """
        )

    def update_state(self, state: SimulationRuntimeState) -> None:
        self.status_value.setText(state.status)
        self.time_value.setText(f"{state.current_time:.1f}")
        self.vehicle_value.setText(str(state.vehicle_count))
        self.speed_value.setText("-" if state.average_speed is None else f"{state.average_speed:.2f}")
        self.message_value.setText(state.message or "")
        self._apply_status_tone(state.status)

    def reset(self) -> None:
        self.update_state(
            SimulationRuntimeState(
                status="idle",
                current_time=0.0,
                vehicle_count=0,
                average_speed=None,
                message="等待生成场景或启动仿真",
            )
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

    def _apply_status_tone(self, status: str) -> None:
        normalized = (status or "").strip().lower()
        tone_map = {
            "running": ("#DBEAFE", "#BFDBFE", "#1D4ED8"),
            "paused": ("#FEF3C7", "#FDE68A", "#B45309"),
            "error": ("#FFE4E6", "#FDA4AF", "#BE123C"),
            "failed": ("#FFE4E6", "#FDA4AF", "#BE123C"),
            "idle": ("#E2E8F0", "#CBD5E1", "#475569"),
        }
        background, border, color = tone_map.get(normalized, ("#E0F2FE", "#BAE6FD", "#0369A1"))
        self.status_value.setStyleSheet(
            f"""
            QLabel#statusBadge {{
                background: {background};
                border: 1px solid {border};
                border-radius: 12px;
                color: {color};
                font-size: 13px;
                font-weight: 600;
                padding: 8px 12px;
                min-height: 36px;
            }}
            """
        )
