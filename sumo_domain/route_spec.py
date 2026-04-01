from __future__ import annotations

from pydantic import BaseModel, Field


class FlowSpec(BaseModel):
    id: str
    from_edge: str
    to_edge: str
    begin: int = 0
    end: int = 3600
    vehs_per_hour: int = 600


class RouteSpec(BaseModel):
    flows: list[FlowSpec] = Field(default_factory=list)
