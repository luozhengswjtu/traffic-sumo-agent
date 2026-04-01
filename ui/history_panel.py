from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from sumo_domain.project_spec import ProjectOperationRecord


class HistoryPanel(QWidget):
    refreshRequested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._records: list[ProjectOperationRecord] = []
        self._build_ui()

    def set_records(self, records: list[ProjectOperationRecord], selected_record_id: int | None = None) -> None:
        self._records = records
        self.history_list.clear()

        if not records:
            self.summary_label.setText("最近操作：0 条")
            self.detail_output.setPlainText("当前没有历史记录。")
            return

        self.summary_label.setText(f"最近操作：{len(records)} 条")
        selected_row = 0
        for index, record in enumerate(records):
            created_at = self._format_time(record.created_at)
            title = f"[{created_at}] {record.intent}"
            item = QListWidgetItem(title)
            item.setData(256, record.id)
            self.history_list.addItem(item)
            if selected_record_id is not None and record.id == selected_record_id:
                selected_row = index

        self.history_list.setCurrentRow(selected_row)
        self._show_record_detail(selected_row)

    def clear_records(self) -> None:
        self._records = []
        self.history_list.clear()
        self.summary_label.setText("最近操作：0 条")
        self.detail_output.setPlainText("当前没有历史记录。")

    def _build_ui(self) -> None:
        wrapper = QGroupBox("操作历史")
        root_layout = QVBoxLayout(self)
        group_layout = QVBoxLayout(wrapper)

        header_layout = QHBoxLayout()
        self.summary_label = QLabel("最近操作：0 条")
        self.refresh_button = QPushButton("刷新")
        self.refresh_button.clicked.connect(self.refreshRequested.emit)
        header_layout.addWidget(self.summary_label)
        header_layout.addStretch(1)
        header_layout.addWidget(self.refresh_button)

        self.history_list = QListWidget()
        self.history_list.currentRowChanged.connect(self._show_record_detail)

        self.detail_output = QPlainTextEdit()
        self.detail_output.setReadOnly(True)
        self.detail_output.setPlaceholderText("选择一条历史记录后，这里会显示详细变更内容。")

        group_layout.addLayout(header_layout)
        group_layout.addWidget(self.history_list, 2)
        group_layout.addWidget(self.detail_output, 3)

        root_layout.addWidget(wrapper)

    def _show_record_detail(self, row: int) -> None:
        if row < 0 or row >= len(self._records):
            if not self._records:
                self.detail_output.setPlainText("当前没有历史记录。")
            return

        record = self._records[row]
        created_at = self._format_time(record.created_at)
        lines = [
            f"时间：{created_at}",
            f"项目：{record.project_name or '未关联项目'}",
            f"意图：{record.intent}",
            f"用户消息：{record.user_message}",
            "",
            "变更摘要：",
            record.change_summary,
        ]

        if record.generated_files:
            lines.extend(["", "生成文件："])
            lines.extend(record.generated_files)
        if record.issues:
            lines.extend(["", "问题："])
            lines.extend(record.issues)

        self.detail_output.setPlainText("\n".join(lines))

    @staticmethod
    def _format_time(value) -> str:
        if isinstance(value, datetime):
            return value.strftime("%Y-%m-%d %H:%M:%S")
        return str(value)
