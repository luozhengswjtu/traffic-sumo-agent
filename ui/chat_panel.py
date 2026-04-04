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

ASSISTANT_NAME = "通通"


class MessageBubble(QFrame):
    ROLE_TITLES = {
        "user": "You",
        "assistant": ASSISTANT_NAME,
        "agent": ASSISTANT_NAME,
        "status": ASSISTANT_NAME,
    }

    def __init__(self, role: str, text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.role = role
        self.raw_text = text
        self.role_label: QLabel | None = None
        self.content_label: QLabel | None = None
        self._build_ui(text)

    def _build_ui(self, text: str) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(6)

        self.role_label = QLabel(self.ROLE_TITLES.get(self.role, ASSISTANT_NAME))
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

    def set_text(self, text: str) -> None:
        self.raw_text = text
        if self.content_label is not None:
            self.content_label.setText(text)

    def apply_width(self, max_width: int) -> None:
        max_width = max(300, max_width)
        min_width = 0
        if len(self.raw_text) >= 14:
            min_width = min(max_width, max(240, int(max_width * 0.42)))
        self.setMaximumWidth(max_width)
        self.setMinimumWidth(min_width)
        if self.content_label is not None:
            self.content_label.setMaximumWidth(max_width - 32)

    def _style_sheet(self) -> str:
        if self.role == "user":
            return """
                QFrame#messageBubbleUser {
                    background: #E9F1FF;
                    border: 1px solid #D5E3FF;
                    border-radius: 18px;
                }
                QLabel#messageRole {
                    color: #5B6B86;
                    font-size: 11px;
                    font-weight: 700;
                }
                QLabel#messageContent {
                    color: #10233D;
                    font-size: 13px;
                    line-height: 1.45;
                }
            """
        if self.role == "status":
            return """
                QFrame#messageBubbleStatus {
                    background: #F6F8FC;
                    border: 1px solid #E4EAF4;
                    border-radius: 18px;
                }
                QLabel#messageRole {
                    color: #64748B;
                    font-size: 11px;
                    font-weight: 700;
                }
                QLabel#messageContent {
                    color: #475569;
                    font-size: 13px;
                }
            """
        return """
            QFrame#messageBubbleAssistant,
            QFrame#messageBubbleAgent {
                background: #FFFFFF;
                border: 1px solid #E6EBF2;
                border-radius: 18px;
            }
            QLabel#messageRole {
                color: #5F6B7A;
                font-size: 11px;
                font-weight: 700;
            }
            QLabel#messageContent {
                color: #0F172A;
                font-size: 13px;
                line-height: 1.48;
            }
        """


class WelcomeCard(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("chatWelcome")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        eyebrow = QLabel("TRAFFIC AGENT")
        eyebrow.setObjectName("welcomeEyebrow")
        title = QLabel(ASSISTANT_NAME)
        title.setObjectName("welcomeTitle")
        description = QLabel(
            "面向 TrafficAgent 的项目助手。普通问题我会直接回答，"
            "工程类请求我会规划工具并把结果整理给你。"
        )
        description.setObjectName("welcomeDescription")
        description.setWordWrap(True)

        examples = QLabel(
            chr(10).join(
                [
                    "试试这些说法：",
                    "- 介绍你自己",
                    "- 当前项目是什么",
                    "- 生成一个双向四车道十字路口，仿真 1800 秒",
                    "- 把流量提高 30% 并运行",
                ]
            )
        )
        examples.setObjectName("welcomeExamples")
        examples.setWordWrap(True)

        layout.addWidget(eyebrow)
        layout.addWidget(title)
        layout.addWidget(description)
        layout.addWidget(examples)

        self.setStyleSheet(
            """
            QFrame#chatWelcome {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #F8FBFF, stop:1 #EEF4FF);
                border: 1px solid #DDE7F5;
                border-radius: 20px;
            }
            QLabel#welcomeEyebrow {
                color: #64748B;
                font-size: 11px;
                font-weight: 700;
                letter-spacing: 0.08em;
            }
            QLabel#welcomeTitle {
                color: #0F172A;
                font-size: 24px;
                font-weight: 700;
            }
            QLabel#welcomeDescription {
                color: #334155;
                font-size: 13px;
            }
            QLabel#welcomeExamples {
                color: #475569;
                font-size: 12px;
                line-height: 1.5;
                background: rgba(255, 255, 255, 0.72);
                border: 1px solid #E3EAF5;
                border-radius: 14px;
                padding: 12px 14px;
            }
            """
        )


class ChatPanel(QWidget):
    messageSubmitted = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        self.scroll_area.setObjectName("chatScroll")

        self.messages_widget = QWidget()
        self.messages_widget.setObjectName("chatStream")
        self.messages_layout = QVBoxLayout(self.messages_widget)
        self.messages_layout.setContentsMargins(6, 6, 6, 8)
        self.messages_layout.setSpacing(12)
        self.messages_layout.addWidget(WelcomeCard())
        self.messages_layout.addStretch(1)
        self.scroll_area.setWidget(self.messages_widget)

        input_shell = QFrame()
        input_shell.setObjectName("inputShell")
        bottom_row = QHBoxLayout(input_shell)
        bottom_row.setContentsMargins(12, 12, 12, 12)
        bottom_row.setSpacing(8)

        self.input_edit = QLineEdit()
        self.input_edit.setPlaceholderText("比如：生成一个双向四车道十字路口，仿真 1800 秒")
        self.input_edit.returnPressed.connect(self.submit_message)
        self.input_edit.setObjectName("chatInput")

        self.send_button = QPushButton("发送")
        self.send_button.clicked.connect(self.submit_message)
        self.send_button.setObjectName("sendButton")

        bottom_row.addWidget(self.input_edit, 1)
        bottom_row.addWidget(self.send_button)

        layout.addWidget(self.scroll_area, 1)
        layout.addWidget(input_shell)
        self._apply_style()

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
        return self._append_message("assistant", text)

    def append_status_message(self, text: str) -> QWidget:
        return self._append_message("status", text)

    def append_agent_placeholder(self, text: str = "通通正在理解你的需求...") -> QWidget:
        return self.append_status_message(text)

    def update_message(self, row_widget: QWidget, role: str, text: str) -> QWidget:
        bubble = row_widget.findChild(MessageBubble)
        if bubble is None or bubble.role != role:
            return self.replace_message(row_widget, role, text)
        bubble.set_text(text)
        self._update_bubble_widths()
        self._scroll_to_bottom()
        return row_widget

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
        row_layout.setContentsMargins(4, 0, 4, 0)
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
        viewport_width = max(340, self.scroll_area.viewport().width())
        bubble_width = max(340, min(780, int(viewport_width * 0.74)))
        for bubble in self.findChildren(MessageBubble):
            bubble.apply_width(bubble_width)

    def _scroll_to_bottom(self) -> None:
        scroll_bar = self.scroll_area.verticalScrollBar()
        scroll_bar.setValue(scroll_bar.maximum())

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_bubble_widths()

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
            QWidget {
                background: transparent;
            }
            QScrollArea#chatScroll {
                background: #F7FAFD;
                border: none;
            }
            QWidget#chatStream {
                background: #F7FAFD;
            }
            QFrame#inputShell {
                background: #FFFFFF;
                border: 1px solid #E3EAF4;
                border-radius: 18px;
            }
            QLineEdit#chatInput {
                background: #FFFFFF;
                border: none;
                color: #0F172A;
                padding: 10px 4px;
                font-size: 13px;
            }
            QLineEdit#chatInput:focus {
                border: none;
            }
            QPushButton#sendButton {
                min-height: 40px;
                min-width: 72px;
                background: #111827;
                color: #FFFFFF;
                border: none;
                border-radius: 14px;
                padding: 10px 14px;
                font-weight: 700;
            }
            QPushButton#sendButton:hover {
                background: #1F2937;
            }
            QPushButton#sendButton:disabled {
                background: #CBD5E1;
                color: #F8FAFC;
            }
            """
        )
