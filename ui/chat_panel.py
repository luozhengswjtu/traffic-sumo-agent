from __future__ import annotations

from pathlib import Path
import html
import re

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFileDialog,
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

from agent.image_models import ImageAnalysisResult
from sumo_domain.project_spec import DirectionalLaneConfig

ASSISTANT_NAME = "\u901a\u901a"


class MarkdownLabel(QLabel):
    HEADING_SIZES = {1: 20, 2: 18, 3: 16, 4: 14}

    def __init__(self, role: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.role = role
        self.setObjectName("messageMarkdown")
        self.setWordWrap(True)
        self.setTextFormat(Qt.RichText)
        self.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.LinksAccessibleByMouse)
        self.setOpenExternalLinks(True)
        self.setFocusPolicy(Qt.NoFocus)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        self.setContentsMargins(0, 0, 0, 0)
        self.setStyleSheet(
            """
            QLabel#messageMarkdown {
                background: transparent;
                border: none;
                padding: 0;
                margin: 0;
            }
            """
        )

    def set_markdown_text(self, text: str) -> None:
        self.setText(self._render_markdown_html(text))
        self.sync_layout()

    def sync_layout(self) -> None:
        self.updateGeometry()
        self.adjustSize()

    def _render_markdown_html(self, text: str) -> str:
        normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip("\n")
        if not normalized:
            return self._render_paragraph("")

        blocks: list[str] = []
        paragraph_lines: list[str] = []
        quote_lines: list[str] = []
        list_items: list[tuple[str, str]] = []
        code_lines: list[str] = []
        code_language = ""
        in_code_block = False

        def flush_paragraph() -> None:
            nonlocal paragraph_lines
            if not paragraph_lines:
                return
            content = " ".join(line.strip() for line in paragraph_lines if line.strip())
            blocks.append(self._render_paragraph(self._render_inline(content)))
            paragraph_lines = []

        def flush_quote() -> None:
            nonlocal quote_lines
            if not quote_lines:
                return
            content = "<br/>".join(self._render_inline(line.strip()) for line in quote_lines if line.strip())
            blocks.append(self._render_quote(content))
            quote_lines = []

        def flush_list() -> None:
            nonlocal list_items
            if not list_items:
                return
            items_html = "".join(self._render_list_item(marker, self._render_inline(content)) for marker, content in list_items)
            blocks.append(items_html)
            list_items = []

        def flush_code() -> None:
            nonlocal code_lines, code_language
            if not code_lines and not code_language:
                return
            blocks.append(self._render_code_block("\n".join(code_lines), code_language))
            code_lines = []
            code_language = ""

        for raw_line in normalized.split("\n"):
            stripped = raw_line.strip()
            fence_match = re.match(r"^```\s*([A-Za-z0-9_+-]+)?\s*$", stripped)
            if in_code_block:
                if stripped.startswith("```"):
                    in_code_block = False
                    flush_code()
                else:
                    code_lines.append(raw_line)
                continue
            if fence_match:
                flush_paragraph()
                flush_quote()
                flush_list()
                in_code_block = True
                code_language = fence_match.group(1) or ""
                code_lines = []
                continue
            if not stripped:
                flush_paragraph()
                flush_quote()
                flush_list()
                continue
            heading_match = re.match(r"^(#{1,4})\s+(.*)$", stripped)
            if heading_match:
                flush_paragraph()
                flush_quote()
                flush_list()
                level = len(heading_match.group(1))
                blocks.append(self._render_heading(level, self._render_inline(heading_match.group(2).strip())))
                continue
            if stripped in {"---", "***", "___"}:
                flush_paragraph()
                flush_quote()
                flush_list()
                blocks.append(self._render_rule())
                continue
            quote_match = re.match(r"^>\s?(.*)$", stripped)
            if quote_match:
                flush_paragraph()
                flush_list()
                quote_lines.append(quote_match.group(1))
                continue
            ordered_match = re.match(r"^(\d+)\.\s+(.*)$", stripped)
            if ordered_match:
                flush_paragraph()
                flush_quote()
                list_items.append((ordered_match.group(1) + ".", ordered_match.group(2)))
                continue
            bullet_match = re.match(r"^[-*+]\s+(.*)$", stripped)
            if bullet_match:
                flush_paragraph()
                flush_quote()
                list_items.append(("bullet", bullet_match.group(1)))
                continue
            flush_quote()
            flush_list()
            paragraph_lines.append(raw_line)

        if in_code_block:
            flush_code()
        flush_paragraph()
        flush_quote()
        flush_list()

        return "".join(blocks)

    def _render_inline(self, text: str) -> str:
        placeholders: list[str] = []

        def hold(fragment: str) -> str:
            token = f"\uFFF0{len(placeholders)}\uFFF1"
            placeholders.append(fragment)
            return token

        linked = re.sub(
            r"\[([^\]]+)\]\(([^)]+)\)",
            lambda match: hold(
                f'<a href="{html.escape(match.group(2).strip(), quote=True)}" style="color:#2563EB; text-decoration:none;">{html.escape(match.group(1).strip())}</a>'
            ),
            text,
        )
        coded = re.sub(
            r"`([^`\n]+)`",
            lambda match: hold(self._render_inline_code(match.group(1))),
            linked,
        )
        escaped = html.escape(coded)
        escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
        escaped = re.sub(r"__(.+?)__", r"<strong>\1</strong>", escaped)
        for index, fragment in enumerate(placeholders):
            escaped = escaped.replace(f"\uFFF0{index}\uFFF1", fragment)
        return escaped

    def _render_heading(self, level: int, content: str) -> str:
        size = self.HEADING_SIZES.get(level, 14)
        return (
            f'<div style="margin: 2px 0 8px 0; color: {self._text_color()}; '
            f'font-size: {size}px; font-weight: 700;">{content}</div>'
        )

    def _render_paragraph(self, content: str) -> str:
        return (
            f'<div style="margin: 0 0 8px 0; color: {self._text_color()}; '
            f'font-size: 13px; line-height: 1.55;">{content or "&nbsp;"}</div>'
        )

    def _render_list_item(self, marker: str, content: str) -> str:
        marker_html = "&#8226;" if marker == "bullet" else html.escape(marker)
        return (
            '<table cellspacing="0" cellpadding="0" style="margin: 0 0 6px 0;">'
            '<tr>'
            f'<td valign="top" style="width: 16px; color: {self._muted_color()}; font-size: 13px; font-weight: 600; padding: 0 6px 0 0;">{marker_html}</td>'
            f'<td valign="top" style="color: {self._text_color()}; font-size: 13px; line-height: 1.55;">{content}</td>'
            '</tr>'
            '</table>'
        )

    def _render_quote(self, content: str) -> str:
        return (
            '<table cellspacing="0" cellpadding="0" style="margin: 2px 0 8px 0;">'
            '<tr>'
            f'<td style="width: 3px; background: {self._quote_border()};"></td>'
            '<td style="width: 8px;"></td>'
            f'<td style="color: {self._muted_color()}; font-size: 13px; line-height: 1.55;">{content}</td>'
            '</tr>'
            '</table>'
        )

    def _render_code_block(self, code: str, language: str) -> str:
        language_html = ""
        if language:
            language_html = (
                f'<div style="margin: 0 0 6px 0; color: {self._muted_color()}; font-size: 11px; '
                f'font-weight: 700; text-transform: uppercase; letter-spacing: 0.04em;">{html.escape(language)}</div>'
            )
        code_lines = code.splitlines() or [""]
        code_html = "<br/>".join(html.escape(line.expandtabs(4)).replace(" ", "&nbsp;") for line in code_lines)
        return (
            '<table cellspacing="0" cellpadding="0" style="margin: 2px 0 10px 0;">'
            '<tr>'
            f'<td style="background: {self._code_background()}; border: 1px solid #E2E8F0; border-radius: 12px; padding: 10px 12px;">'
            f'{language_html}'
            f'<div style="color: {self._text_color()}; font-size: 12px; line-height: 1.5; font-family: Consolas, Courier New, monospace;">{code_html}</div>'
            '</td>'
            '</tr>'
            '</table>'
        )

    def _render_inline_code(self, code: str) -> str:
        return (
            f'<span style="background: {self._code_background()}; color: {self._text_color()}; '
            'border-radius: 6px; padding: 1px 4px; font-family: Consolas, Courier New, monospace;">'
            f'{html.escape(code)}</span>'
        )

    def _render_rule(self) -> str:
        return '<div style="height: 1px; background: #E2E8F0; margin: 8px 0;"></div>'

    def _text_color(self) -> str:
        return "#475569" if self.role == "status" else "#0F172A"

    def _muted_color(self) -> str:
        return "#64748B" if self.role == "status" else "#475569"

    def _code_background(self) -> str:
        return "#EEF2F7" if self.role == "status" else "#F8FAFC"

    def _quote_border(self) -> str:
        return "#CBD5E1" if self.role == "status" else "#D7E3F1"


class MessageBubble(QFrame):
    ROLE_TITLES = {"user": "You", "assistant": ASSISTANT_NAME, "agent": ASSISTANT_NAME, "status": ASSISTANT_NAME}

    def __init__(self, role: str, text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.role = role
        self.raw_text = text
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(6)
        self.role_label = QLabel(self.ROLE_TITLES.get(role, ASSISTANT_NAME))
        self.role_label.setObjectName("messageRole")
        if role == "user":
            self.content_widget: QLabel | MarkdownLabel = QLabel(text)
            self.content_widget.setWordWrap(True)
            self.content_widget.setTextFormat(Qt.PlainText)
            self.content_widget.setTextInteractionFlags(Qt.TextSelectableByMouse)
        else:
            self.content_widget = MarkdownLabel(role)
            self.content_widget.set_markdown_text(text)
        self.content_widget.setObjectName("messageContent")
        layout.addWidget(self.role_label)
        layout.addWidget(self.content_widget)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        self.setObjectName(f"messageBubble{role.title()}")
        self.setStyleSheet(self._style_sheet())

    def set_text(self, text: str) -> None:
        self.raw_text = text
        if isinstance(self.content_widget, QLabel):
            self.content_widget.setText(text)
            return
        self.content_widget.set_markdown_text(text)

    def apply_width(self, max_width: int) -> None:
        max_width = max(320, max_width)
        self.setMaximumWidth(max_width)
        self.content_widget.setMaximumWidth(max_width - 32)
        if isinstance(self.content_widget, MarkdownLabel):
            self.content_widget.sync_layout()

    def _style_sheet(self) -> str:
        if self.role == "user":
            return """QFrame#messageBubbleUser { background: #E9F1FF; border: 1px solid #D5E3FF; border-radius: 18px; } QLabel#messageRole { color: #5B6B86; font-size: 11px; font-weight: 700; } QLabel#messageContent { color: #10233D; font-size: 13px; line-height: 1.45; }"""
        if self.role == "status":
            return """QFrame#messageBubbleStatus { background: #F6F8FC; border: 1px solid #E4EAF4; border-radius: 18px; } QLabel#messageRole { color: #64748B; font-size: 11px; font-weight: 700; } QLabel#messageContent { color: #475569; font-size: 13px; }"""
        return """QFrame#messageBubbleAssistant, QFrame#messageBubbleAgent { background: #FFFFFF; border: 1px solid #E6EBF2; border-radius: 18px; } QLabel#messageRole { color: #5F6B7A; font-size: 11px; font-weight: 700; } QLabel#messageContent { color: #0F172A; font-size: 13px; line-height: 1.48; }"""


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
        description = QLabel("\u9762\u5411 TrafficAgent \u7684\u9879\u76ee\u52a9\u624b\u3002\u666e\u901a\u95ee\u9898\u6211\u4f1a\u76f4\u63a5\u56de\u7b54\uff0c\u5de5\u7a0b\u8bf7\u6c42\u6211\u4f1a\u89c4\u5212\u5de5\u5177\u5e76\u628a\u7ed3\u679c\u6574\u7406\u7ed9\u4f60\u3002")
        description.setObjectName("welcomeDescription")
        description.setWordWrap(True)
        examples = QLabel("\u5c1d\u8bd5\u8fd9\u4e9b\u8bf4\u6cd5\uff1a\n- \u4ecb\u7ecd\u4f60\u81ea\u5df1\n- \u5f53\u524d\u9879\u76ee\u662f\u4ec0\u4e48\n- \u751f\u6210\u4e00\u4e2a\u53cc\u5411\u56db\u8f66\u9053\u5341\u5b57\u8def\u53e3\uff0c\u4eff\u771f 1800 \u79d2\n- \u628a\u6d41\u91cf\u63d0\u9ad8 30% \u5e76\u8fd0\u884c\n- \u4e0a\u4f20\u4e00\u5f20\u8def\u53e3\u4fde\u89c6\u56fe\uff0c\u5e2e\u6211\u8bc6\u522b\u6210 SUMO \u8def\u53e3")
        examples.setObjectName("welcomeExamples")
        examples.setWordWrap(True)
        layout.addWidget(eyebrow)
        layout.addWidget(title)
        layout.addWidget(description)
        layout.addWidget(examples)
        self.setStyleSheet("""QFrame#chatWelcome { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #F8FBFF, stop:1 #EEF4FF); border: 1px solid #DDE7F5; border-radius: 20px; } QLabel#welcomeEyebrow { color: #64748B; font-size: 11px; font-weight: 700; letter-spacing: 0.08em; } QLabel#welcomeTitle { color: #0F172A; font-size: 24px; font-weight: 700; } QLabel#welcomeDescription { color: #334155; font-size: 13px; } QLabel#welcomeExamples { color: #475569; font-size: 12px; background: rgba(255, 255, 255, 0.72); border: 1px solid #E3EAF5; border-radius: 14px; padding: 12px 14px; }""")


class ImageBubble(QFrame):
    def __init__(self, image_path: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("imageBubble")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)
        title = QLabel("\u5df2\u4e0a\u4f20\u56fe\u7247")
        title.setObjectName("imageTitle")
        pixmap = QPixmap(image_path)
        preview = QLabel()
        preview.setObjectName("imagePreview")
        preview.setAlignment(Qt.AlignCenter)
        if not pixmap.isNull():
            preview.setPixmap(pixmap.scaled(260, 180, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        meta = QLabel(Path(image_path).name)
        meta.setObjectName("imageMeta")
        meta.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(preview)
        layout.addWidget(meta)
        self.setStyleSheet("""QFrame#imageBubble { background: #FFFFFF; border: 1px solid #E6EBF2; border-radius: 18px; } QLabel#imageTitle { color: #475569; font-size: 11px; font-weight: 700; } QLabel#imageMeta { color: #334155; font-size: 12px; } QLabel#imagePreview { background: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 14px; min-height: 120px; }""")


class DraftPreviewCard(QFrame):
    confirmRequested = Signal()
    customizeRequested = Signal()
    cancelRequested = Signal()
    reuploadRequested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("draftCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        self.status_label = QLabel("\u56fe\u7247\u8349\u7a3f")
        self.status_label.setObjectName("draftTitle")
        self.summary_label = QLabel()
        self.summary_label.setWordWrap(True)
        self.summary_label.setObjectName("draftSummary")
        self.details_label = QLabel()
        self.details_label.setWordWrap(True)
        self.details_label.setObjectName("draftDetails")
        button_row = QHBoxLayout()
        button_row.setSpacing(8)
        self.confirm_button = QPushButton("\u786e\u8ba4\u751f\u6210")
        self.confirm_button.setObjectName("draftConfirmButton")
        self.customize_button = QPushButton("\u81ea\u5b9a\u4e49")
        self.customize_button.setObjectName("draftCustomizeButton")
        self.cancel_button = QPushButton("\u53d6\u6d88\u8349\u7a3f")
        self.cancel_button.setObjectName("draftCancelButton")
        self.reupload_button = QPushButton("\u91cd\u65b0\u4e0a\u4f20")
        self.reupload_button.setObjectName("draftReuploadButton")
        self.confirm_button.clicked.connect(self.confirmRequested.emit)
        self.customize_button.clicked.connect(self.customizeRequested.emit)
        self.cancel_button.clicked.connect(self.cancelRequested.emit)
        self.reupload_button.clicked.connect(self.reuploadRequested.emit)
        for button in (self.confirm_button, self.customize_button, self.cancel_button, self.reupload_button):
            button_row.addWidget(button)
        button_row.addStretch(1)
        layout.addWidget(self.status_label)
        layout.addWidget(self.summary_label)
        layout.addWidget(self.details_label)
        layout.addLayout(button_row)
        self.setStyleSheet(
            """QFrame#draftCard { background: #FFFFFF; border: 1px solid #E6EBF2; border-radius: 18px; }
            QLabel#draftTitle { color: #0F172A; font-size: 14px; font-weight: 700; }
            QLabel#draftSummary { color: #334155; font-size: 13px; }
            QLabel#draftDetails { color: #475569; font-size: 12px; background: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 14px; padding: 10px 12px; }
            QPushButton { min-height: 34px; border-radius: 10px; padding: 6px 12px; font-weight: 600; }
            QPushButton#draftConfirmButton { background: #111827; color: #FFFFFF; border: 1px solid #111827; }
            QPushButton#draftConfirmButton:hover { background: #1F2937; border-color: #1F2937; }
            QPushButton#draftCustomizeButton { background: #FFFFFF; color: #0F172A; border: 1px solid #CBD5E1; }
            QPushButton#draftCustomizeButton:hover { background: #F8FAFC; border-color: #94A3B8; }
            QPushButton#draftCancelButton, QPushButton#draftReuploadButton { background: #F8FAFC; color: #334155; border: 1px solid #D7E0EC; }
            QPushButton#draftCancelButton:hover, QPushButton#draftReuploadButton:hover { background: #EEF2F7; border-color: #B8C4D6; }
            QPushButton:disabled { background: #E2E8F0; color: #94A3B8; border: 1px solid #E2E8F0; }"""
        )

    def update_result(self, result: ImageAnalysisResult) -> None:
        self.summary_label.setText(result.reply_text)
        draft = result.draft
        if draft is None:
            self.status_label.setText("\u56fe\u7247\u8bc6\u522b\u7ed3\u679c")
            self.details_label.setText("\u6ca1\u6709\u53ef\u7f16\u8f91\u7684\u8349\u7a3f\u3002")
        else:
            details = ["\u7c7b\u578b\uff1a" + (draft.topology or "\u672a\u8bc6\u522b")]
            if draft.directional_lanes.has_any():
                lane_text = "\uff1b".join(f"{DirectionalLaneConfig.edge_label(edge_id)} {getattr(draft.directional_lanes, edge_id)}" for edge_id in DirectionalLaneConfig.valid_edge_ids(draft.topology) if getattr(draft.directional_lanes, edge_id) is not None)
                details.append(f"\u8f66\u9053\uff1a{lane_text}")
            if draft.road_length_m is not None:
                details.append(f"\u957f\u5ea6\uff1a{draft.road_length_m:.0f} m")
            if draft.speed_limit_kmh is not None:
                details.append(f"\u9650\u901f\uff1a{draft.speed_limit_kmh:.0f} km/h")
            if draft.confidence is not None:
                details.append(f"\u7f6e\u4fe1\u5ea6\uff1a{draft.confidence:.2f}")
            self.status_label.setText(f"\u8def\u53e3\u8349\u7a3f \xb7 {draft.image_name()}")
            self.details_label.setText("\n".join(details))
        self.confirm_button.setVisible(result.allow_confirm)
        self.customize_button.setVisible(result.allow_customize)
        self.cancel_button.setVisible(result.draft is not None)
        self.reupload_button.setVisible(result.allow_reupload)


class ChatPanel(QWidget):
    messageSubmitted = Signal(str)
    imageSelected = Signal(str)
    draftConfirmRequested = Signal()
    draftCustomizeRequested = Signal()
    draftCancelRequested = Signal()
    draftReuploadRequested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._draft_row: QWidget | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        self.messages_widget = QWidget()
        self.messages_layout = QVBoxLayout(self.messages_widget)
        self.messages_layout.setContentsMargins(6, 6, 6, 8)
        self.messages_layout.setSpacing(12)
        self.messages_layout.addWidget(WelcomeCard())
        self.messages_layout.addStretch(1)
        self.scroll_area.setWidget(self.messages_widget)
        shell = QFrame()
        shell.setObjectName("inputShell")
        bottom = QHBoxLayout(shell)
        bottom.setContentsMargins(12, 12, 12, 12)
        bottom.setSpacing(8)
        self.upload_button = QPushButton("\u4e0a\u4f20\u56fe\u7247")
        self.upload_button.setObjectName("uploadButton")
        self.upload_button.clicked.connect(self._choose_image)
        self.input_edit = QLineEdit()
        self.input_edit.setPlaceholderText("\u4f8b\u5982\uff1a\u751f\u6210\u4e00\u4e2a\u53cc\u5411\u56db\u8f66\u9053\u5341\u5b57\u8def\u53e3\uff0c\u4eff\u771f 1800 \u79d2")
        self.input_edit.returnPressed.connect(self.submit_message)
        self.input_edit.setObjectName("chatInput")
        self.send_button = QPushButton("\u53d1\u9001")
        self.send_button.setObjectName("sendButton")
        self.send_button.clicked.connect(self.submit_message)
        bottom.addWidget(self.upload_button)
        bottom.addWidget(self.input_edit, 1)
        bottom.addWidget(self.send_button)
        layout.addWidget(self.scroll_area, 1)
        layout.addWidget(shell)
        self._apply_style()

    def submit_message(self) -> None:
        text = self.input_edit.text().strip()
        if not text:
            return
        self.append_user_message(text)
        self.input_edit.clear()
        self.messageSubmitted.emit(text)

    def set_busy(self, busy: bool) -> None:
        self.input_edit.setDisabled(busy)
        self.send_button.setDisabled(busy)
        self.upload_button.setDisabled(busy)
        self.send_button.setText("\u5904\u7406\u4e2d..." if busy else "\u53d1\u9001")

    def append_user_message(self, text: str) -> QWidget:
        return self._append_widget(MessageBubble("user", text), align_right=True)

    def append_agent_message(self, text: str) -> QWidget:
        return self._append_widget(MessageBubble("assistant", text))

    def append_status_message(self, text: str) -> QWidget:
        return self._append_widget(MessageBubble("status", text))

    def append_image_message(self, image_path: str) -> QWidget:
        return self._append_widget(ImageBubble(image_path), align_right=True)

    def show_draft_preview(self, result: ImageAnalysisResult) -> QWidget:
        card = DraftPreviewCard()
        card.update_result(result)
        card.confirmRequested.connect(self.draftConfirmRequested.emit)
        card.customizeRequested.connect(self.draftCustomizeRequested.emit)
        card.cancelRequested.connect(self.draftCancelRequested.emit)
        card.reuploadRequested.connect(self.draftReuploadRequested.emit)
        self._draft_row = self._append_widget(card) if self._draft_row is None else self.replace_widget(self._draft_row, card)
        return self._draft_row

    def clear_draft_preview(self) -> None:
        if self._draft_row is None:
            return
        self.messages_layout.removeWidget(self._draft_row)
        self._draft_row.deleteLater()
        self._draft_row = None
        self._scroll_to_bottom()

    def update_message(self, row_widget: QWidget, role: str, text: str) -> QWidget:
        bubble = row_widget.findChild(MessageBubble)
        if bubble is None or bubble.role != role:
            return self.replace_widget(row_widget, MessageBubble(role, text))
        bubble.set_text(text)
        self._update_bubble_widths()
        self._scroll_to_bottom()
        return row_widget

    def replace_message(self, row_widget: QWidget, role: str, text: str) -> QWidget:
        return self.replace_widget(row_widget, MessageBubble(role, text))

    def replace_widget(self, row_widget: QWidget, inner: QWidget) -> QWidget:
        index = self.messages_layout.indexOf(row_widget)
        if index < 0:
            return self._append_widget(inner)
        self.messages_layout.removeWidget(row_widget)
        row_widget.deleteLater()
        new_row = self._wrap_widget(inner, isinstance(inner, MessageBubble) and inner.role == "user")
        self.messages_layout.insertWidget(index, new_row)
        self._update_bubble_widths()
        self._scroll_to_bottom()
        return new_row

    def _append_widget(self, inner: QWidget, align_right: bool = False) -> QWidget:
        row = self._wrap_widget(inner, align_right)
        self.messages_layout.insertWidget(self.messages_layout.count() - 1, row)
        self._update_bubble_widths()
        self._scroll_to_bottom()
        return row

    def _wrap_widget(self, inner: QWidget, align_right: bool) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(4, 0, 4, 0)
        if align_right:
            layout.addStretch(1)
            layout.addWidget(inner, 0, Qt.AlignRight)
        else:
            layout.addWidget(inner, 0, Qt.AlignLeft)
            layout.addStretch(1)
        return row

    def _choose_image(self) -> None:
        image_path, _ = QFileDialog.getOpenFileName(self, "\u9009\u62e9\u8def\u53e3\u56fe\u7247", "", "Images (*.png *.jpg *.jpeg *.webp)")
        if image_path:
            self.imageSelected.emit(image_path)

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
        self.setStyleSheet("""QWidget { background: transparent; } QFrame#inputShell { background: #FFFFFF; border: 1px solid #E3EAF4; border-radius: 18px; } QLineEdit#chatInput { background: #FFFFFF; border: none; color: #0F172A; padding: 10px 4px; font-size: 13px; } QPushButton#sendButton, QPushButton#uploadButton { min-height: 40px; border-radius: 14px; padding: 10px 14px; font-weight: 700; } QPushButton#sendButton { background: #111827; color: #FFFFFF; border: none; } QPushButton#uploadButton { background: #FFFFFF; color: #0F172A; border: 1px solid #CBD5E1; } QPushButton#sendButton:disabled, QPushButton#uploadButton:disabled { background: #CBD5E1; color: #F8FAFC; border-color: #CBD5E1; }""")
