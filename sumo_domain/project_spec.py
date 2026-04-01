from __future__ import annotations

from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field

from sumo_domain.network_spec import NetworkSpec
from sumo_domain.route_spec import RouteSpec
from sumo_domain.simulation_spec import SimulationSpec


class ProjectMeta(BaseModel):
    name: str
    project_dir: Path
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    description: str | None = None


class ProjectScenarioState(BaseModel):
    scenario_type: str = "intersection"
    lane_count: int = 2
    road_length: float = 200.0
    speed_limit: float = 13.89
    flow_level: str = "medium"
    flow_rate: int | None = None
    traffic_bias: str | None = None
    duration_seconds: int = 1800
    step_length: float = 1.0
    seed: int | None = None


class ProjectContext(BaseModel):
    meta: ProjectMeta
    network: NetworkSpec | None = None
    routes: RouteSpec | None = None
    simulation: SimulationSpec | None = None
    scenario_state: ProjectScenarioState | None = None


class ProjectOperationRecord(BaseModel):
    id: int | None = None
    created_at: datetime = Field(default_factory=datetime.now)
    project_name: str | None = None
    project_dir: str | None = None
    intent: str
    user_message: str
    change_summary: str
    before_state: dict | None = None
    after_state: dict | None = None
    generated_files: list[str] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)


class RecentProjectItem(BaseModel):
    name: str
    project_dir: str
    last_opened_at: datetime = Field(default_factory=datetime.now)
