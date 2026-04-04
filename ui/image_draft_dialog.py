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
        self.setWindowTitle("???????")
        self.setModal(True)
        self.resize(560, 540)
        self._lane_spins: dict[str, QSpinBox] = {}
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

        title = QLabel("???????")
        title.setObjectName("dialogTitle")
        hint = QLabel("?????????????????????????????")
        hint.setObjectName("dialogHint")
        hint.setWordWrap(True)

        form = QFormLayout()
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(12)
        form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        self.topology_combo = QComboBox()
        self.topology_combo.addItem("????", "intersection")
        self.topology_combo.addItem("T ???", "t_junction")
        self.topology_combo.addItem("????", "corridor")
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

        form.addRow("????", self.topology_combo)
        form.addRow("????", self.length_spin)
        form.addRow("??", self.speed_spin)

        lane_title = QLabel("????")
        lane_title.setObjectName("sectionTitle")
        lane_grid = QGridLayout()
        lane_grid.setHorizontalSpacing(12)
        lane_grid.setVerticalSpacing(10)

        for index, edge_id in enumerate(DirectionalLaneConfig.EDGE_ORDER):
            label = QLabel(DirectionalLaneConfig.edge_label(edge_id))
            label.setObjectName("fieldLabel")
            spin = QSpinBox()
            spin.setRange(1, 8)
            spin.setValue(2)
            self._lane_spins[edge_id] = spin
            lane_grid.addWidget(label, index, 0)
            lane_grid.addWidget(spin, index, 1)

        shell_layout.addWidget(title)
        shell_layout.addWidget(hint)
        shell_layout.addLayout(form)
        shell_layout.addWidget(lane_title)
        shell_layout.addLayout(lane_grid)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
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
        lane_data = {edge_id: spin.value() for edge_id, spin in self._lane_spins.items() if spin.isEnabled()}
        return IntersectionImageDraft(
            source_image_path=source_image_path,
            topology=topology,
            is_intersection=True,
            is_supported_for_generation=topology in {"intersection", "t_junction", "corridor"},
            directional_lanes=DirectionalLaneConfig(**lane_data),
            road_length_m=self.length_spin.value(),
            speed_limit_kmh=self.speed_spin.value(),
            confidence=None,
            reason="?????????",
        )

    def _update_lane_spin_visibility(self) -> None:
        topology = self.topology_combo.currentData()
        valid_ids = set(DirectionalLaneConfig.valid_edge_ids(topology))
        for edge_id, spin in self._lane_spins.items():
            enabled = edge_id in valid_ids
            spin.setEnabled(enabled)
            spin.parentWidget()
