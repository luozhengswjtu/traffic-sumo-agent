from __future__ import annotations

from pydantic import BaseModel


class AppConfig(BaseModel):
    app_name: str = "TrafficAgent"
    locale: str = "zh-CN"
    last_project_path: str | None = None
    projects_root: str = "workspace/projects"
    autosave_enabled: bool = True


class ModelConfig(BaseModel):
    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""
    model: str = "gpt-4.1-mini"
    temperature: float = 0.2
    timeout_seconds: int = 60


class UserPreferences(BaseModel):
    default_scenario_type: str = "intersection"
    default_flow_level: str = "medium"
    default_duration: int = 1800
    system_prompt_additions: str | None = None
