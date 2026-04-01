from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


class MessageBubble(QFrame):
    def __init__(self, role: str, text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.role = role
        self._build_ui(text)

    def _build_ui(self, text: str) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(6)

        role_label = QLabel("你" if self.role == "user" else "TrafficAgent")
        role_label.setObjectName(f"messageRole{self.role.title()}")

        content_label = QLabel(text)
        content_label.setWordWrap(True)
        content_label.setTextInteractionFlags(Qt.TextSelectableByMouse)

        layout.addWidget(role_label)
        layout.addWidget(content_label)

        self.setFrameShape(QFrame.StyledPanel)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        self.setMaximumWidth(520)
        self._apply_style()

    def _apply_style(self) -> None:
        palette = self.palette()
        if self.role == "user":
            background = QColor("#D8F0FF")
            border = "#8AC8E8"
        else:
            background = QColor("#F3F5F7")
            border = "#D4D9DE"
        palette.setColor(QPalette.Window, background)
        self.setAutoFillBackground(True)
        self.setPalette(palette)
        self.setStyleSheet(
            f"QFrame {{ border: 1px solid {border}; border-radius: 14px; }} "
            "QLabel { color: #1F2933; font-size: 13px; }"
            "QLabel#messageRoleUser, QLabel#messageRoleAgent { font-weight: 600; font-size: 12px; }"
        )


class ChatPanel(QWidget):
    messageSubmitted = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        title = QLabel("对话区")
        title.setObjectName("chatPanelTitle")

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self.messages_widget = QWidget()
        self.messages_layout = QVBoxLayout(self.messages_widget)
        self.messages_layout.setContentsMargins(10, 10, 10, 10)
        self.messages_layout.setSpacing(10)
        self.messages_layout.addStretch(1)
        self.scroll_area.setWidget(self.messages_widget)

        bottom_row = QHBoxLayout()
        self.input_edit = QLineEdit()
        self.input_edit.setPlaceholderText("例如：生成一个双向四车道十字路口，仿真 1800 秒")
        self.input_edit.returnPressed.connect(self.submit_message)

        self.send_button = QPushButton("发送")
        self.send_button.clicked.connect(self.submit_message)

        bottom_row.addWidget(self.input_edit, 1)
        bottom_row.addWidget(self.send_button)

        hint = QLabel("支持生成、编辑、运行、查看历史。更自然的中文表达也可以直接试。")
        hint.setWordWrap(True)
        hint.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)

        layout.addWidget(title)
        layout.addWidget(self.scroll_area, 1)
        layout.addLayout(bottom_row)
        layout.addWidget(hint)

    def submit_message(self) -> None:
        text = self.input_edit.text().strip()
        if not text:
            return
        self.append_user_message(text)
        self.input_edit.clear()
        self.messageSubmitted.emit(text)

    def append_user_message(self, text: str) -> None:
        self._append_message("user", text)

    def append_agent_message(self, text: str) -> None:
        self._append_message("agent", text)

    def set_busy(self, busy: bool) -> None:
        self.input_edit.setDisabled(busy)
        self.send_button.setDisabled(busy)
        self.send_button.setText("处理中..." if busy else "发送")

    def _append_message(self, role: str, text: str) -> None:
        row_widget = QWidget()
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(0)

        bubble = MessageBubble(role, text)
        if role == "user":
            row_layout.addStretch(1)
            row_layout.addWidget(bubble)
        else:
            row_layout.addWidget(bubble)
            row_layout.addStretch(1)

        self.messages_layout.insertWidget(self.messages_layout.count() - 1, row_widget)
        self._scroll_to_bottom()

    def _scroll_to_bottom(self) -> None:
        scroll_bar = self.scroll_area.verticalScrollBar()
        scroll_bar.setValue(scroll_bar.maximum())
