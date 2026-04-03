from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QFrame,
    QFormLayout,
    QGridLayout,
    QLabel,
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
        layout.setContentsMargins(0, 0, 0, 0)

        card = QFrame()
        card.setObjectName("controlCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(18, 18, 18, 18)
        card_layout.setSpacing(14)

        title = QLabel("运行控制")
        title.setObjectName("panelTitle")
        hint = QLabel("右侧保留操作效率，但整体层级和留白与聊天区保持协调。")
        hint.setObjectName("panelHint")
        hint.setWordWrap(True)

        form_panel = QFrame()
        form_panel.setObjectName("surfacePanel")
        form = QFormLayout(form_panel)
        form.setContentsMargins(14, 14, 14, 14)
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(12)
        form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        form.setFormAlignment(Qt.AlignLeft | Qt.AlignTop)

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

        form.addRow(self._make_form_label("仿真时长（秒）"), self.duration_spin)
        form.addRow(self._make_form_label("仿真步长"), self.step_length_spin)
        form.addRow(self._make_form_label("随机种子"), self.seed_spin)
        form.addRow(self._make_form_label("流量占位值"), self.flow_level_spin)

        action_label = QLabel("执行操作")
        action_label.setObjectName("sectionLabel")

        action_grid = QGridLayout()
        action_grid.setHorizontalSpacing(10)
        action_grid.setVerticalSpacing(10)

        self.run_button = QPushButton("运行")
        self.pause_button = QPushButton("暂停")
        self.resume_button = QPushButton("继续")
        self.step_button = QPushButton("单步")
        self.stop_button = QPushButton("停止")

        self.run_button.setObjectName("primaryAction")
        self.pause_button.setObjectName("secondaryAction")
        self.resume_button.setObjectName("secondaryAction")
        self.step_button.setObjectName("secondaryAction")
        self.stop_button.setObjectName("dangerAction")

        self.run_button.clicked.connect(self.runRequested.emit)
        self.pause_button.clicked.connect(self.pauseRequested.emit)
        self.resume_button.clicked.connect(self.resumeRequested.emit)
        self.step_button.clicked.connect(self.stepRequested.emit)
        self.stop_button.clicked.connect(self.stopRequested.emit)

        action_grid.addWidget(self.run_button, 0, 0, 1, 2)
        action_grid.addWidget(self.pause_button, 1, 0)
        action_grid.addWidget(self.resume_button, 1, 1)
        action_grid.addWidget(self.step_button, 2, 0)
        action_grid.addWidget(self.stop_button, 2, 1)

        card_layout.addWidget(title)
        card_layout.addWidget(hint)
        card_layout.addWidget(form_panel)
        card_layout.addWidget(action_label)
        card_layout.addLayout(action_grid)

        layout.addWidget(card)

        self.setStyleSheet(
            """
            QFrame#controlCard {
                background: #F8FAFC;
                border: 1px solid #E2E8F0;
                border-radius: 18px;
            }
            QFrame#surfacePanel {
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
            QLabel#formLabel {
                color: #475569;
                font-size: 12px;
                font-weight: 600;
            }
            QSpinBox,
            QDoubleSpinBox {
                background: #FFFFFF;
                border: 1px solid #CBD5E1;
                border-radius: 10px;
                padding: 7px 10px;
                min-height: 36px;
                color: #0F172A;
            }
            QSpinBox:focus,
            QDoubleSpinBox:focus {
                border-color: #94A3B8;
            }
            QPushButton {
                min-height: 38px;
                border-radius: 12px;
                padding: 8px 14px;
                font-weight: 600;
            }
            QPushButton#primaryAction {
                background: #0F172A;
                color: #FFFFFF;
                border: none;
            }
            QPushButton#primaryAction:hover {
                background: #1E293B;
            }
            QPushButton#secondaryAction {
                background: #FFFFFF;
                color: #0F172A;
                border: 1px solid #CBD5E1;
            }
            QPushButton#secondaryAction:hover {
                background: #F8FAFC;
                border-color: #94A3B8;
            }
            QPushButton#dangerAction {
                background: #FFF1F2;
                color: #BE123C;
                border: 1px solid #FDA4AF;
            }
            QPushButton#dangerAction:hover {
                background: #FFE4E6;
            }
            QPushButton:disabled {
                background: #E2E8F0;
                color: #94A3B8;
                border-color: #E2E8F0;
            }
            """
        )

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

    @staticmethod
    def _make_form_label(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("formLabel")
        return label
