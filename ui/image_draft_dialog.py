from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QLabel,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from agent.image_models import IntersectionImageDraft
from sumo_domain.project_spec import DirectionalLaneConfig


class ImageDraftDialog(QDialog):
    def __init__(self, draft: IntersectionImageDraft, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("\u7f16\u8f91\u8def\u53e3\u8349\u7a3f")
        self.setModal(True)
        self.resize(560, 540)
        self._lane_spins: dict[str, QSpinBox] = {}
        self._lane_labels: dict[str, QLabel] = {}
        self._build_ui()
        self.load_draft(draft)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(14)

        shell = QFrame()
        shell.setObjectName("draftDialogShell")
        shell_layout = QVBoxLayout(shell)
        shell_layout.setContentsMargins(18, 18, 18, 18)
        shell_layout.setSpacing(14)

        title = QLabel("\u7f16\u8f91\u8def\u53e3\u8349\u7a3f")
        title.setObjectName("dialogTitle")
        hint = QLabel("\u4f60\u53ef\u4ee5\u624b\u52a8\u8865\u9f50\u62d3\u6251\u3001\u957f\u5ea6\u3001\u9650\u901f\u548c\u5404\u65b9\u5411\u8fdb\u51fa\u53e3\u8f66\u9053\u6570\u3002\u4fdd\u5b58\u540e\uff0c\u804a\u5929\u91cc\u7684\u9884\u89c8\u5361\u4f1a\u540c\u6b65\u66f4\u65b0\u3002")
        hint.setObjectName("dialogHint")
        hint.setWordWrap(True)

        form = QFormLayout()
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(12)
        form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        self.topology_combo = QComboBox()
        self.topology_combo.addItem("\u5341\u5b57\u8def\u53e3", "intersection")
        self.topology_combo.addItem("T \u5b57\u8def\u53e3", "t_junction")
        self.topology_combo.addItem("\u76f4\u7ebf\u8def\u6bb5", "corridor")
        self.topology_combo.currentIndexChanged.connect(self._update_lane_spin_visibility)

        self.length_spin = QDoubleSpinBox()
        self.length_spin.setRange(20.0, 3000.0)
        self.length_spin.setDecimals(1)
        self.length_spin.setSingleStep(10.0)
        self.length_spin.setSuffix(" m")

        self.speed_spin = QDoubleSpinBox()
        self.speed_spin.setRange(5.0, 120.0)
        self.speed_spin.setDecimals(1)
        self.speed_spin.setSingleStep(5.0)
        self.speed_spin.setSuffix(" km/h")

        form.addRow("\u8def\u53e3\u7c7b\u578b", self.topology_combo)
        form.addRow("\u9053\u8def\u957f\u5ea6", self.length_spin)
        form.addRow("\u9650\u901f", self.speed_spin)

        lane_title = QLabel("\u65b9\u5411\u8f66\u9053\u914d\u7f6e")
        lane_title.setObjectName("sectionTitle")
        lane_hint = QLabel("\u53ea\u4f1a\u663e\u793a\u5f53\u524d\u62d3\u6251\u9700\u8981\u7684\u65b9\u5411\u8f66\u9053\u5b57\u6bb5\u3002")
        lane_hint.setObjectName("dialogHint")
        lane_hint.setWordWrap(True)

        lane_grid = QGridLayout()
        lane_grid.setHorizontalSpacing(12)
        lane_grid.setVerticalSpacing(10)

        for index, edge_id in enumerate(DirectionalLaneConfig.EDGE_ORDER):
            label = QLabel(DirectionalLaneConfig.edge_label(edge_id))
            label.setObjectName("fieldLabel")
            spin = QSpinBox()
            spin.setRange(1, 8)
            spin.setValue(2)
            self._lane_labels[edge_id] = label
            self._lane_spins[edge_id] = spin
            lane_grid.addWidget(label, index, 0)
            lane_grid.addWidget(spin, index, 1)

        shell_layout.addWidget(title)
        shell_layout.addWidget(hint)
        shell_layout.addLayout(form)
        shell_layout.addWidget(lane_title)
        shell_layout.addWidget(lane_hint)
        shell_layout.addLayout(lane_grid)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        save_button = buttons.button(QDialogButtonBox.Save)
        cancel_button = buttons.button(QDialogButtonBox.Cancel)
        if save_button is not None:
            save_button.setText("\u4fdd\u5b58")
            save_button.setObjectName("dialogPrimaryButton")
        if cancel_button is not None:
            cancel_button.setText("\u53d6\u6d88")
            cancel_button.setObjectName("dialogSecondaryButton")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        root.addWidget(shell)
        root.addWidget(buttons)

        self.setStyleSheet(
            """
            QDialog {
                background: #F5F7FB;
            }
            QFrame#draftDialogShell {
                background: #FFFFFF;
                border: 1px solid #E2E8F0;
                border-radius: 18px;
            }
            QLabel#dialogTitle {
                color: #0F172A;
                font-size: 18px;
                font-weight: 700;
            }
            QLabel#dialogHint,
            QLabel#fieldLabel,
            QLabel#sectionTitle {
                color: #475569;
                font-size: 12px;
                font-weight: 600;
            }
            QComboBox,
            QDoubleSpinBox,
            QSpinBox {
                min-height: 36px;
                border-radius: 10px;
                border: 1px solid #CBD5E1;
                background: #FFFFFF;
                padding: 6px 10px;
                color: #0F172A;
            }
            QPushButton {
                min-height: 36px;
                border-radius: 10px;
                padding: 8px 16px;
                font-weight: 600;
                border: 1px solid #CBD5E1;
                background: #FFFFFF;
                color: #0F172A;
            }
            QPushButton#dialogPrimaryButton {
                background: #111827;
                color: #FFFFFF;
                border-color: #111827;
            }
            QPushButton#dialogPrimaryButton:hover {
                background: #1F2937;
                border-color: #1F2937;
            }
            QPushButton#dialogSecondaryButton {
                background: #F8FAFC;
                color: #334155;
                border-color: #CBD5E1;
            }
            QPushButton#dialogSecondaryButton:hover {
                background: #EEF2F7;
                border-color: #94A3B8;
            }
            """
        )

    def load_draft(self, draft: IntersectionImageDraft) -> None:
        current_index = self.topology_combo.findData(draft.topology or "intersection")
        if current_index >= 0:
            self.topology_combo.setCurrentIndex(current_index)
        if draft.road_length_m is not None:
            self.length_spin.setValue(float(draft.road_length_m))
        if draft.speed_limit_kmh is not None:
            self.speed_spin.setValue(float(draft.speed_limit_kmh))
        for edge_id, spin in self._lane_spins.items():
            value = getattr(draft.directional_lanes, edge_id)
            if value is not None:
                spin.setValue(int(value))
        self._update_lane_spin_visibility()

    def collect_draft(self, source_image_path: str) -> IntersectionImageDraft:
        topology = self.topology_combo.currentData()
        valid_ids = set(DirectionalLaneConfig.valid_edge_ids(topology))
        lane_data = {
            edge_id: spin.value()
            for edge_id, spin in self._lane_spins.items()
            if edge_id in valid_ids and spin.isEnabled()
        }
        return IntersectionImageDraft(
            source_image_path=source_image_path,
            topology=topology,
            is_intersection=True,
            is_supported_for_generation=topology in {"intersection", "t_junction", "corridor"},
            directional_lanes=DirectionalLaneConfig(**lane_data),
            road_length_m=self.length_spin.value(),
            speed_limit_kmh=self.speed_spin.value(),
            confidence=None,
            reason="\u7528\u6237\u901a\u8fc7\u81ea\u5b9a\u4e49\u5f39\u7a97\u624b\u52a8\u4fee\u8ba2\u4e86\u8def\u53e3\u8349\u7a3f\u3002",
        )

    def _update_lane_spin_visibility(self) -> None:
        topology = self.topology_combo.currentData()
        valid_ids = set(DirectionalLaneConfig.valid_edge_ids(topology))
        for edge_id, spin in self._lane_spins.items():
            visible = edge_id in valid_ids
            self._lane_labels[edge_id].setVisible(visible)
            spin.setVisible(visible)
            spin.setEnabled(visible)
