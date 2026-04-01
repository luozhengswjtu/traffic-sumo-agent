from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from sumo_domain.simulation_spec import SimulationSpec


class ControlPanel(QWidget):
    simulationParamsChanged = Signal(object)
    runRequested = Signal()
    pauseRequested = Signal()
    resumeRequested = Signal()
    stepRequested = Signal()
    stopRequested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._build_ui()
        self.load_simulation_spec(SimulationSpec())

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        group = QGroupBox("参数面板")
        form = QFormLayout(group)

        self.duration_spin = QSpinBox()
        self.duration_spin.setRange(60, 86400)
        self.duration_spin.setSingleStep(60)
        self.duration_spin.valueChanged.connect(self._emit_params_changed)

        self.step_length_spin = QDoubleSpinBox()
        self.step_length_spin.setRange(0.1, 10.0)
        self.step_length_spin.setSingleStep(0.1)
        self.step_length_spin.setDecimals(2)
        self.step_length_spin.valueChanged.connect(self._emit_params_changed)

        self.seed_spin = QSpinBox()
        self.seed_spin.setRange(0, 999999)
        self.seed_spin.setSpecialValueText("自动")
        self.seed_spin.valueChanged.connect(self._emit_params_changed)

        self.flow_level_spin = QSpinBox()
        self.flow_level_spin.setRange(100, 5000)
        self.flow_level_spin.setSingleStep(100)

        form.addRow("仿真时长(秒)", self.duration_spin)
        form.addRow("仿真步长", self.step_length_spin)
        form.addRow("随机种子", self.seed_spin)
        form.addRow("流量占位值", self.flow_level_spin)

        primary_button_row = QHBoxLayout()
        self.run_button = QPushButton("运行")
        self.pause_button = QPushButton("暂停")
        self.resume_button = QPushButton("继续")
        self.step_button = QPushButton("单步")
        self.stop_button = QPushButton("停止")

        self.run_button.clicked.connect(self.runRequested.emit)
        self.pause_button.clicked.connect(self.pauseRequested.emit)
        self.resume_button.clicked.connect(self.resumeRequested.emit)
        self.step_button.clicked.connect(self.stepRequested.emit)
        self.stop_button.clicked.connect(self.stopRequested.emit)

        primary_button_row.addWidget(self.run_button)
        primary_button_row.addWidget(self.pause_button)
        primary_button_row.addWidget(self.resume_button)

        secondary_button_row = QHBoxLayout()
        secondary_button_row.addWidget(self.step_button)
        secondary_button_row.addWidget(self.stop_button)
        secondary_button_row.addStretch(1)

        layout.addWidget(group)
        layout.addLayout(primary_button_row)
        layout.addLayout(secondary_button_row)
        layout.addStretch(1)

    def load_simulation_spec(self, spec: SimulationSpec) -> None:
        self.duration_spin.setValue(spec.end_time)
        self.step_length_spin.setValue(spec.step_length)
        if spec.seed is None:
            self.seed_spin.setValue(self.seed_spin.minimum())
        else:
            self.seed_spin.setValue(spec.seed)

    def collect_simulation_spec(self) -> SimulationSpec:
        seed_value = self.seed_spin.value()
        seed = None if seed_value == self.seed_spin.minimum() else seed_value
        return SimulationSpec(
            begin_time=0,
            end_time=self.duration_spin.value(),
            step_length=self.step_length_spin.value(),
            seed=seed,
        )

    def set_run_enabled(self, enabled: bool) -> None:
        self.run_button.setEnabled(enabled)

    def _emit_params_changed(self) -> None:
        self.simulationParamsChanged.emit(self.collect_simulation_spec())
