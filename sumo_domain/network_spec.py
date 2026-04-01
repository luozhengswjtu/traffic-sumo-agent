from __future__ import annotations

from pydantic import BaseModel, Field


class NodeSpec(BaseModel):
    id: str
    x: float
    y: float
    type: str = "priority"


class EdgeSpec(BaseModel):
    id: str
    from_node: str
    to_node: str
    num_lanes: int = 1
    speed: float = 13.89
    length: float | None = None


class NetworkSpec(BaseModel):
    scenario_type: str
    nodes: list[NodeSpec] = Field(default_factory=list)
    edges: list[EdgeSpec] = Field(default_factory=list)
