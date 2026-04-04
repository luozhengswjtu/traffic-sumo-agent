from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
)

from sumo_domain.preferences import ModelConfig, UserPreferences


class SettingsDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.resize(520, 460)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.base_url_edit = QLineEdit()
        self.api_key_edit = QLineEdit()
        self.model_edit = QLineEdit()
        self.supports_vision_check = QCheckBox("当前模型支持图片识别")
        self.default_scenario_edit = QLineEdit()
        self.default_flow_edit = QLineEdit()
        self.default_duration_spin = QSpinBox()
        self.default_duration_spin.setRange(60, 86400)
        self.prompt_additions_edit = QTextEdit()
        self.prompt_additions_edit.setPlaceholderText("可选：记录你的额外偏好")

        form.addRow("Base URL", self.base_url_edit)
        form.addRow("API Key", self.api_key_edit)
        form.addRow("模型名", self.model_edit)
        form.addRow("视觉能力", self.supports_vision_check)
        form.addRow("默认场景", self.default_scenario_edit)
        form.addRow("默认流量", self.default_flow_edit)
        form.addRow("默认时长", self.default_duration_spin)
        form.addRow("额外偏好", self.prompt_additions_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout.addLayout(form)
        layout.addWidget(buttons)

    def load_settings(self, model_config: ModelConfig, user_preferences: UserPreferences) -> None:
        self.base_url_edit.setText(model_config.base_url)
        self.api_key_edit.setText(model_config.api_key)
        self.model_edit.setText(model_config.model)
        self.supports_vision_check.setChecked(model_config.supports_vision)
        self.default_scenario_edit.setText(user_preferences.default_scenario_type)
        self.default_flow_edit.setText(user_preferences.default_flow_level)
        self.default_duration_spin.setValue(user_preferences.default_duration)
        self.prompt_additions_edit.setPlainText(user_preferences.system_prompt_additions or "")

    def collect_model_config(self) -> ModelConfig:
        return ModelConfig(
            base_url=self.base_url_edit.text().strip() or ModelConfig().base_url,
            api_key=self.api_key_edit.text().strip(),
            model=self.model_edit.text().strip() or ModelConfig().model,
            supports_vision=self.supports_vision_check.isChecked(),
        )

    def collect_user_preferences(self) -> UserPreferences:
        additions = self.prompt_additions_edit.toPlainText().strip()
        return UserPreferences(
            default_scenario_type=self.default_scenario_edit.text().strip() or UserPreferences().default_scenario_type,
            default_flow_level=self.default_flow_edit.text().strip() or UserPreferences().default_flow_level,
            default_duration=self.default_duration_spin.value(),
            system_prompt_additions=additions or None,
        )
