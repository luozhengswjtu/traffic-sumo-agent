from __future__ import annotations

from enum import Enum


class UserIntent(str, Enum):
    CREATE_SCENARIO = "create_scenario"
    EDIT_SCENARIO = "edit_scenario"
    RUN_SIMULATION = "run_simulation"
    UPDATE_PREFERENCES = "update_preferences"
    SUMMARIZE_PROJECT = "summarize_project"
    VIEW_HISTORY = "view_history"
    UNKNOWN = "unknown"
