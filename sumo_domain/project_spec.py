from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import ClassVar

from pydantic import BaseModel, Field

from sumo_domain.network_spec import NetworkSpec
from sumo_domain.route_spec import RouteSpec
from sumo_domain.simulation_spec import SimulationSpec


class DirectionalLaneConfig(BaseModel):
    EDGE_ORDER: ClassVar[tuple[str, ...]] = ("north_in", "north_out", "south_in", "south_out", "west_in", "west_out", "east_in", "east_out")
    EDGE_LABELS: ClassVar[dict[str, str]] = {
        "north_in": "\u5317\u5411\u5165\u53e3",
        "north_out": "\u5317\u5411\u51fa\u53e3",
        "south_in": "\u5357\u5411\u5165\u53e3",
        "south_out": "\u5357\u5411\u51fa\u53e3",
        "west_in": "\u897f\u5411\u5165\u53e3",
        "west_out": "\u897f\u5411\u51fa\u53e3",
        "east_in": "\u4e1c\u5411\u5165\u53e3",
        "east_out": "\u4e1c\u5411\u51fa\u53e3",
    }
    TOPOLOGY_EDGE_IDS: ClassVar[dict[str, tuple[str, ...]]] = {
        "intersection": EDGE_ORDER,
        "t_junction": ("north_in", "north_out", "west_in", "west_out", "east_in", "east_out"),
        "corridor": ("west_in", "west_out", "east_in", "east_out"),
    }

    north_in: int | None = None
    north_out: int | None = None
    south_in: int | None = None
    south_out: int | None = None
    west_in: int | None = None
    west_out: int | None = None
    east_in: int | None = None
    east_out: int | None = None

    @classmethod
    def valid_edge_ids(cls, scenario_type: str | None) -> tuple[str, ...]:
        return cls.TOPOLOGY_EDGE_IDS.get(scenario_type or "", cls.EDGE_ORDER)

    @classmethod
    def edge_label(cls, edge_id: str) -> str:
        return cls.EDGE_LABELS.get(edge_id, edge_id)

    def has_any(self) -> bool:
        return any(getattr(self, edge_id) is not None for edge_id in self.EDGE_ORDER)

    def values_for_topology(self, scenario_type: str | None) -> dict[str, int | None]:
        return {edge_id: getattr(self, edge_id) for edge_id in self.valid_edge_ids(scenario_type)}

    def merged_with_fallback(self, scenario_type: str | None, fallback: int) -> "DirectionalLaneConfig":
        data = self.model_dump()
        for edge_id in self.valid_edge_ids(scenario_type):
            if data.get(edge_id) is None:
                data[edge_id] = fallback
        return DirectionalLaneConfig(**data)

    def to_edge_lane_map(self, scenario_type: str | None, fallback: int) -> dict[str, int]:
        merged = self.merged_with_fallback(scenario_type, fallback)
        return {edge_id: int(getattr(merged, edge_id) or fallback) for edge_id in self.valid_edge_ids(scenario_type)}

    def is_complete(self, scenario_type: str | None) -> bool:
        return all(getattr(self, edge_id) is not None for edge_id in self.valid_edge_ids(scenario_type))

    def effective_lane_count(self, scenario_type: str | None, fallback: int) -> int:
        values = [value for value in self.values_for_topology(scenario_type).values() if value is not None]
        if not values:
            return fallback
        return max(max(values), fallback)


class ProjectMeta(BaseModel):
    name: str
    project_dir: Path
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    description: str | None = None


class ProjectScenarioState(BaseModel):
    scenario_type: str = "intersection"
    lane_count: int = 2
    directional_lanes: DirectionalLaneConfig = Field(default_factory=DirectionalLaneConfig)
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
