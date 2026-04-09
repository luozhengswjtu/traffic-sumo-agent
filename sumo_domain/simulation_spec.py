from __future__ import annotations

from pydantic import BaseModel, Field

from sumo_domain.signal_plan import SignalRuntimeStatus


class SimulationSpec(BaseModel):
    begin_time: int = 0
    end_time: int = 1800
    step_length: float = 1.0
    seed: int | None = None
    route_file: str = "scenario.rou.xml"
    net_file: str = "scenario.net.xml"
    additional_files: list[str] = Field(default_factory=list)


class SimulationRuntimeState(BaseModel):
    status: str = "idle"
    current_time: float = 0.0
    vehicle_count: int = 0
    average_speed: float | None = None
    message: str | None = None
    signal_status: SignalRuntimeStatus | None = None
