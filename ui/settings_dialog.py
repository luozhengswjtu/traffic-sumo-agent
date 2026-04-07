from __future__ import annotations

from urllib.parse import urlparse

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QLabel,
    QLineEdit,
    QMessageBox,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
)

from sumo_domain.preferences import ModelConfig, UserPreferences


class SettingsDialog(QDialog):
    SCENARIO_OPTIONS = (
        ("intersection", "\u5341\u5b57\u8def\u53e3"),
        ("t_junction", "T \u5b57\u8def\u53e3"),
        ("corridor", "\u76f4\u7ebf\u8def\u6bb5"),
    )
    FLOW_OPTIONS = (
        ("low", "\u4f4e\u6d41\u91cf"),
        ("medium", "\u4e2d\u6d41\u91cf"),
        ("high", "\u9ad8\u6d41\u91cf"),
        ("very_high", "\u8d85\u9ad8\u6d41\u91cf"),
    )

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("\u6a21\u578b\u4e0e\u504f\u597d\u8bbe\u7f6e")
        self.resize(640, 620)
        self._build_ui()
        self._apply_style()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(14)

        header = QLabel("\u5728\u8fd9\u91cc\u914d\u7f6e OpenAI \u517c\u5bb9\u6a21\u578b\u8fde\u63a5\u53c2\u6570\uff0c\u4ee5\u53ca\u65b0\u5efa\u9879\u76ee\u65f6\u4f7f\u7528\u7684\u9ed8\u8ba4\u504f\u597d\u3002")
        header.setObjectName("settingsHeader")
        header.setWordWrap(True)

        self.base_url_edit = QLineEdit()
        self.base_url_edit.setPlaceholderText("https://api.openai.com/v1")

        self.api_key_edit = QLineEdit()
        self.api_key_edit.setPlaceholderText("sk-...")
        self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)

        self.show_api_key_check = QCheckBox("\u663e\u793a API Key")
        self.show_api_key_check.toggled.connect(self._toggle_api_key_visibility)

        self.model_edit = QLineEdit()
        self.model_edit.setPlaceholderText("gpt-4.1-mini")

        self.temperature_spin = QDoubleSpinBox()
        self.temperature_spin.setRange(0.0, 2.0)
        self.temperature_spin.setSingleStep(0.1)
        self.temperature_spin.setDecimals(2)

        self.timeout_seconds_spin = QSpinBox()
        self.timeout_seconds_spin.setRange(5, 600)
        self.timeout_seconds_spin.setSuffix(" \u79d2")

        self.supports_vision_check = QCheckBox("\u5f53\u524d\u6a21\u578b\u652f\u6301\u56fe\u7247\u8bc6\u522b")

        self.default_scenario_combo = QComboBox()
        for value, label in self.SCENARIO_OPTIONS:
            self.default_scenario_combo.addItem(label, value)

        self.default_flow_combo = QComboBox()
        for value, label in self.FLOW_OPTIONS:
            self.default_flow_combo.addItem(label, value)

        self.default_duration_spin = QSpinBox()
        self.default_duration_spin.setRange(60, 86400)
        self.default_duration_spin.setSingleStep(60)
        self.default_duration_spin.setSuffix(" \u79d2")

        self.prompt_additions_edit = QTextEdit()
        self.prompt_additions_edit.setPlaceholderText("\u53ef\u9009\uff1a\u8bb0\u5f55\u4f60\u7684\u989d\u5916\u504f\u597d\uff0c\u4f8b\u5982\u56de\u590d\u8bed\u6c14\u3001\u7ea6\u675f\u6761\u4ef6\u6216\u5e38\u7528\u8bbe\u5b9a\u3002")
        self.prompt_additions_edit.setMinimumHeight(120)

        layout.addWidget(header)
        layout.addWidget(self._build_model_card())
        layout.addWidget(self._build_preferences_card(), 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        save_button = buttons.button(QDialogButtonBox.StandardButton.Save)
        cancel_button = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        if save_button is not None:
            save_button.setObjectName("primaryButton")
        if cancel_button is not None:
            cancel_button.setObjectName("secondaryButton")
        buttons.accepted.connect(self._accept_with_validation)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _build_model_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("settingsCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        title = QLabel("\u6a21\u578b\u914d\u7f6e")
        title.setObjectName("cardTitle")

        hint = QLabel("\u5f53\u524d\u5b9e\u73b0\u4f7f\u7528 OpenAI \u517c\u5bb9\u63a5\u53e3\u3002Base URL \u901a\u5e38\u4ee5 /v1 \u7ed3\u5c3e\uff0c\u6a21\u578b\u540d\u79f0\u7531\u670d\u52a1\u7aef\u5b9e\u9645\u53ef\u7528\u6a21\u578b\u51b3\u5b9a\u3002")
        hint.setObjectName("cardHint")
        hint.setWordWrap(True)

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(12)

        form.addRow("Base URL", self.base_url_edit)
        form.addRow("API Key", self.api_key_edit)
        form.addRow("", self.show_api_key_check)
        form.addRow("\u6a21\u578b\u540d\u79f0", self.model_edit)
        form.addRow("Temperature", self.temperature_spin)
        form.addRow("\u8d85\u65f6\u65f6\u95f4", self.timeout_seconds_spin)
        form.addRow("\u89c6\u89c9\u80fd\u529b", self.supports_vision_check)

        layout.addWidget(title)
        layout.addWidget(hint)
        layout.addLayout(form)
        return card

    def _build_preferences_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("settingsCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        title = QLabel("\u9ed8\u8ba4\u504f\u597d")
        title.setObjectName("cardTitle")

        hint = QLabel("\u8fd9\u4e9b\u8bbe\u7f6e\u4f1a\u5f71\u54cd\u65b0\u5efa\u9879\u76ee\u3001\u9690\u5f0f\u8fd0\u884c\u9879\u76ee\u4ee5\u53ca\u7cfb\u7edf\u63d0\u793a\u7684\u9ed8\u8ba4\u884c\u4e3a\u3002")
        hint.setObjectName("cardHint")
        hint.setWordWrap(True)

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(12)

        form.addRow("\u9ed8\u8ba4\u573a\u666f", self.default_scenario_combo)
        form.addRow("\u9ed8\u8ba4\u6d41\u91cf", self.default_flow_combo)
        form.addRow("\u9ed8\u8ba4\u65f6\u957f", self.default_duration_spin)
        form.addRow("\u989d\u5916\u504f\u597d", self.prompt_additions_edit)

        layout.addWidget(title)
        layout.addWidget(hint)
        layout.addLayout(form)
        return card

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
            QDialog {
                background: #F5F7FB;
            }
            QLabel#settingsHeader {
                color: #475569;
                font-size: 12px;
            }
            QFrame#settingsCard {
                background: #FBFCFE;
                border: 1px solid #E2E8F0;
                border-radius: 18px;
            }
            QLabel#cardTitle {
                color: #0F172A;
                font-size: 15px;
                font-weight: 600;
            }
            QLabel#cardHint {
                color: #64748B;
                font-size: 12px;
            }
            QLineEdit,
            QComboBox,
            QSpinBox,
            QDoubleSpinBox,
            QTextEdit {
                background: #FFFFFF;
                color: #0F172A;
                border: 1px solid #CBD5E1;
                border-radius: 10px;
                padding: 7px 10px;
            }
            QLineEdit:focus,
            QComboBox:focus,
            QSpinBox:focus,
            QDoubleSpinBox:focus,
            QTextEdit:focus {
                border-color: #94A3B8;
            }
            QComboBox::drop-down {
                border: none;
                width: 28px;
            }
            QCheckBox {
                color: #334155;
            }
            QDialogButtonBox QPushButton {
                min-width: 92px;
                min-height: 36px;
                border-radius: 10px;
                padding: 8px 14px;
                font-weight: 600;
            }
            QDialogButtonBox QPushButton#primaryButton {
                background: #0F172A;
                color: #FFFFFF;
                border: none;
            }
            QDialogButtonBox QPushButton#secondaryButton {
                background: #FFFFFF;
                color: #0F172A;
                border: 1px solid #CBD5E1;
            }
            """
        )

    def load_settings(self, model_config: ModelConfig, user_preferences: UserPreferences) -> None:
        self.base_url_edit.setText(model_config.base_url)
        self.api_key_edit.setText(model_config.api_key)
        self.model_edit.setText(model_config.model)
        self.temperature_spin.setValue(model_config.temperature)
        self.timeout_seconds_spin.setValue(model_config.timeout_seconds)
        self.supports_vision_check.setChecked(model_config.supports_vision)
        self._set_combo_value(self.default_scenario_combo, user_preferences.default_scenario_type)
        self._set_combo_value(self.default_flow_combo, user_preferences.default_flow_level)
        self.default_duration_spin.setValue(user_preferences.default_duration)
        self.prompt_additions_edit.setPlainText(user_preferences.system_prompt_additions or "")

    def collect_model_config(self) -> ModelConfig:
        defaults = ModelConfig()
        return ModelConfig(
            base_url=self.base_url_edit.text().strip() or defaults.base_url,
            api_key=self.api_key_edit.text().strip(),
            model=self.model_edit.text().strip() or defaults.model,
            supports_vision=self.supports_vision_check.isChecked(),
            temperature=self.temperature_spin.value(),
            timeout_seconds=self.timeout_seconds_spin.value(),
        )

    def collect_user_preferences(self) -> UserPreferences:
        defaults = UserPreferences()
        additions = self.prompt_additions_edit.toPlainText().strip()
        return UserPreferences(
            default_scenario_type=self.default_scenario_combo.currentData() or defaults.default_scenario_type,
            default_flow_level=self.default_flow_combo.currentData() or defaults.default_flow_level,
            default_duration=self.default_duration_spin.value(),
            system_prompt_additions=additions or None,
        )

    def _accept_with_validation(self) -> None:
        model_config = self.collect_model_config()
        parsed = urlparse(model_config.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            QMessageBox.warning(self, "\u914d\u7f6e\u65e0\u6548", "Base URL \u5fc5\u987b\u662f\u5b8c\u6574\u7684 http \u6216 https \u5730\u5740\u3002")
            self.base_url_edit.setFocus()
            return
        if not model_config.model.strip():
            QMessageBox.warning(self, "\u914d\u7f6e\u65e0\u6548", "\u6a21\u578b\u540d\u79f0\u4e0d\u80fd\u4e3a\u7a7a\u3002")
            self.model_edit.setFocus()
            return
        self.accept()

    def _toggle_api_key_visibility(self, checked: bool) -> None:
        echo_mode = QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
        self.api_key_edit.setEchoMode(echo_mode)

    @staticmethod
    def _set_combo_value(combo: QComboBox, value: str) -> None:
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)
