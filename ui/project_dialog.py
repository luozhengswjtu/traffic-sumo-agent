from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QFileDialog,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class NewProjectDialog(QDialog):
    def __init__(self, default_dir: Path, parent=None) -> None:
        super().__init__(parent)
        self.default_dir = default_dir
        self.setWindowTitle("新建项目")
        self.resize(520, 180)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.name_edit = QLineEdit()
        self.path_edit = QLineEdit(str(self.default_dir))

        browse_container = QWidget()
        browse_row = QHBoxLayout(browse_container)
        browse_row.setContentsMargins(0, 0, 0, 0)
        browse_row.addWidget(self.path_edit, 1)
        browse_button = QPushButton("浏览")
        browse_button.clicked.connect(self._browse_directory)
        browse_row.addWidget(browse_button)

        form.addRow("项目名称", self.name_edit)
        form.addRow("保存目录", browse_container)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout.addLayout(form)
        layout.addWidget(buttons)

    def _browse_directory(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "选择项目目录", self.path_edit.text())
        if directory:
            self.path_edit.setText(directory)

    def collect_project_name(self) -> str:
        return self.name_edit.text().strip()

    def collect_project_path(self) -> Path:
        return Path(self.path_edit.text().strip())
