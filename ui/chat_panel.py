from __future__ import annotations

from PySide6.QtCore import Qt, Signal
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
        self.raw_text = text
        self.role_label: QLabel | None = None
        self.content_label: QLabel | None = None
        self._build_ui(text)

    def _build_ui(self, text: str) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(6)

        self.role_label = QLabel("You" if self.role == "user" else "TrafficAgent")
        self.role_label.setObjectName("messageRole")

        self.content_label = QLabel(text)
        self.content_label.setObjectName("messageContent")
        self.content_label.setWordWrap(True)
        self.content_label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.content_label.setTextFormat(Qt.PlainText)
        self.content_label.setTextInteractionFlags(Qt.TextSelectableByMouse)

        layout.addWidget(self.role_label)
        layout.addWidget(self.content_label)

        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        self.setObjectName(f"messageBubble{self.role.title()}")
        self.setStyleSheet(self._style_sheet())

    def apply_width(self, max_width: int) -> None:
        max_width = max(320, max_width)
        min_width = 0
        if len(self.raw_text) >= 14:
            min_width = min(max_width, max(260, int(max_width * 0.48)))

        self.setMaximumWidth(max_width)
        self.setMinimumWidth(min_width)
        if self.content_label is not None:
            self.content_label.setMaximumWidth(max_width - 32)

    def _style_sheet(self) -> str:
        if self.role == "user":
            return """
                QFrame#messageBubbleUser {
                    background: #EEF2FF;
                    border: 1px solid #D9E2FF;
                    border-radius: 16px;
                }
                QLabel#messageRole {
                    color: #6B7280;
                    font-size: 11px;
                    font-weight: 600;
                }
                QLabel#messageContent {
                    color: #111827;
                    font-size: 13px;
                }
            """
        return """
            QFrame#messageBubbleAgent {
                background: #FFFFFF;
                border: 1px solid #E5E7EB;
                border-radius: 16px;
            }
            QLabel#messageRole {
                color: #6B7280;
                font-size: 11px;
                font-weight: 600;
            }
            QLabel#messageContent {
                color: #111827;
                font-size: 13px;
            }
        """


class ChatPanel(QWidget):
    messageSubmitted = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        title = QLabel("对话")
        title.setObjectName("chatPanelTitle")
        title.setStyleSheet("color: #111827; font-size: 14px; font-weight: 600;")

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        self.scroll_area.setStyleSheet(
            "QScrollArea { background: #F8FAFC; border: 1px solid #E5E7EB; border-radius: 14px; }"
            "QWidget { background: #F8FAFC; }"
        )

        self.messages_widget = QWidget()
        self.messages_layout = QVBoxLayout(self.messages_widget)
        self.messages_layout.setContentsMargins(18, 18, 18, 18)
        self.messages_layout.setSpacing(12)
        self.messages_layout.addStretch(1)
        self.scroll_area.setWidget(self.messages_widget)

        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(8)

        self.input_edit = QLineEdit()
        self.input_edit.setPlaceholderText("例如：生成一个双向四车道十字路口，仿真 1800 秒")
        self.input_edit.returnPressed.connect(self.submit_message)
        self.input_edit.setStyleSheet(
            "QLineEdit { background: #FFFFFF; border: 1px solid #D1D5DB; border-radius: 12px; padding: 10px 12px; color: #111827; }"
            "QLineEdit:focus { border-color: #9CA3AF; }"
        )

        self.send_button = QPushButton("发送")
        self.send_button.clicked.connect(self.submit_message)
        self.send_button.setStyleSheet(
            "QPushButton { background: #111827; color: #FFFFFF; border: none; border-radius: 12px; padding: 10px 16px; font-weight: 600; }"
            "QPushButton:disabled { background: #9CA3AF; color: #F9FAFB; }"
        )

        bottom_row.addWidget(self.input_edit, 1)
        bottom_row.addWidget(self.send_button)

        layout.addWidget(title)
        layout.addWidget(self.scroll_area, 1)
        layout.addLayout(bottom_row)

    def submit_message(self) -> None:
        text = self.input_edit.text().strip()
        if not text:
            return
        self.append_user_message(text)
        self.input_edit.clear()
        self.messageSubmitted.emit(text)

    def append_user_message(self, text: str) -> QWidget:
        return self._append_message("user", text)

    def append_agent_message(self, text: str) -> QWidget:
        return self._append_message("agent", text)

    def append_agent_placeholder(self, text: str = "TrafficAgent 正在思考...") -> QWidget:
        return self._append_message("agent", text)

    def replace_message(self, row_widget: QWidget, role: str, text: str) -> QWidget:
        index = self.messages_layout.indexOf(row_widget)
        if index < 0:
            return self._append_message(role, text)

        self.messages_layout.removeWidget(row_widget)
        row_widget.deleteLater()
        new_row = self._create_message_row(role, text)
        self.messages_layout.insertWidget(index, new_row)
        self._update_bubble_widths()
        self._scroll_to_bottom()
        return new_row

    def set_busy(self, busy: bool) -> None:
        self.input_edit.setDisabled(busy)
        self.send_button.setDisabled(busy)
        self.send_button.setText("处理中..." if busy else "发送")

    def _append_message(self, role: str, text: str) -> QWidget:
        row_widget = self._create_message_row(role, text)
        self.messages_layout.insertWidget(self.messages_layout.count() - 1, row_widget)
        self._update_bubble_widths()
        self._scroll_to_bottom()
        return row_widget

    def _create_message_row(self, role: str, text: str) -> QWidget:
        row_widget = QWidget()
        row_widget.setStyleSheet("background: transparent;")
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(6, 0, 6, 0)
        row_layout.setSpacing(0)

        bubble = MessageBubble(role, text)
        if role == "user":
            row_layout.addStretch(1)
            row_layout.addWidget(bubble, 0, Qt.AlignRight)
        else:
            row_layout.addWidget(bubble, 0, Qt.AlignLeft)
            row_layout.addStretch(1)
        return row_widget

    def _update_bubble_widths(self) -> None:
        viewport_width = max(360, self.scroll_area.viewport().width())
        bubble_width = max(360, min(840, int(viewport_width * 0.76)))
        for bubble in self.findChildren(MessageBubble):
            bubble.apply_width(bubble_width)

    def _scroll_to_bottom(self) -> None:
        scroll_bar = self.scroll_area.verticalScrollBar()
        scroll_bar.setValue(scroll_bar.maximum())

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_bubble_widths()
