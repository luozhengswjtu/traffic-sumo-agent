from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, TypeVar

from pydantic import BaseModel

from sumo_domain.preferences import AppConfig, ModelConfig, UserPreferences

T = TypeVar("T", bound=BaseModel)


class AppConfigStore:
    """Persist app-level settings under the local config directory."""

    def __init__(self, config_dir: Path) -> None:
        self.config_dir = config_dir
        self.config_dir.mkdir(parents=True, exist_ok=True)

    def load_app_config(self) -> AppConfig:
        return self._load_model("app_config.json", AppConfig, AppConfig)

    def save_app_config(self, config: AppConfig) -> None:
        self._save_model("app_config.json", config)

    def load_model_config(self) -> ModelConfig:
        return self._load_model("model_config.json", ModelConfig, ModelConfig)

    def save_model_config(self, config: ModelConfig) -> None:
        self._save_model("model_config.json", config)

    def load_user_preferences(self) -> UserPreferences:
        return self._load_model("user_preferences.json", UserPreferences, UserPreferences)

    def save_user_preferences(self, preferences: UserPreferences) -> None:
        self._save_model("user_preferences.json", preferences)

    def _load_model(
        self,
        filename: str,
        model_type: type[T],
        default_factory: Callable[[], T],
    ) -> T:
        file_path = self.config_dir / filename
        if not file_path.exists():
            default_value = default_factory()
            self._save_model(filename, default_value)
            return default_value

        data = json.loads(file_path.read_text(encoding="utf-8"))
        return model_type.model_validate(data)

    def _save_model(self, filename: str, model: BaseModel) -> None:
        file_path = self.config_dir / filename
        file_path.write_text(
            json.dumps(model.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
