from __future__ import annotations

from pydantic import BaseModel, Field


class SimulationEvent(BaseModel):
    type: str
    payload: dict = Field(default_factory=dict)
