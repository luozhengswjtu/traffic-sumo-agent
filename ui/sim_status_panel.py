from __future__ import annotations

from PySide6.QtWidgets import QFormLayout, QGroupBox, QLabel, QVBoxLayout, QWidget

from sumo_domain.simulation_spec import SimulationRuntimeState


class SimulationStatusPanel(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._build_ui()
        self.reset()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        group = QGroupBox("仿真状态")
        form = QFormLayout(group)

        self.status_value = QLabel("idle")
        self.time_value = QLabel("0.0")
        self.vehicle_value = QLabel("0")
        self.speed_value = QLabel("-")
        self.message_value = QLabel("尚未开始仿真")
        self.message_value.setWordWrap(True)

        form.addRow("状态", self.status_value)
        form.addRow("当前时间", self.time_value)
        form.addRow("车辆数", self.vehicle_value)
        form.addRow("平均速度", self.speed_value)
        form.addRow("说明", self.message_value)

        layout.addWidget(group)

    def update_state(self, state: SimulationRuntimeState) -> None:
        self.status_value.setText(state.status)
        self.time_value.setText(f"{state.current_time:.1f}")
        self.vehicle_value.setText(str(state.vehicle_count))
        self.speed_value.setText("-" if state.average_speed is None else f"{state.average_speed:.2f}")
        self.message_value.setText(state.message or "")

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
