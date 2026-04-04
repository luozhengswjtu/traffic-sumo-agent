from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from sumo_domain.project_spec import DirectionalLaneConfig

ASSISTANT_NAME = "\u901a\u901a"
SUPPORTED_TOPOLOGIES = {"intersection", "t_junction", "corridor"}


class ImageAnalysisStatus(str, Enum):
    DRAFT_READY = "draft_ready"
    NOT_INTERSECTION = "not_intersection"
    UNSUPPORTED_TOPOLOGY = "unsupported_topology"
    INVALID_RESULT = "invalid_result"


class IntersectionImageDraft(BaseModel):
    source_image_path: str
    topology: str | None = None
    is_intersection: bool = False
    is_supported_for_generation: bool = False
    directional_lanes: DirectionalLaneConfig = Field(default_factory=DirectionalLaneConfig)
    road_length_m: float | None = None
    speed_limit_kmh: float | None = None
    confidence: float | None = None
    reason: str = ""

    def image_name(self) -> str:
        return Path(self.source_image_path).name

    def missing_fields(self) -> list[str]:
        missing: list[str] = []
        if self.topology not in SUPPORTED_TOPOLOGIES:
            missing.append("topology")
            return missing
        if not self.directional_lanes.is_complete(self.topology):
            for edge_id, value in self.directional_lanes.values_for_topology(self.topology).items():
                if value is None:
                    missing.append(edge_id)
        if self.road_length_m is None:
            missing.append("road_length_m")
        if self.speed_limit_kmh is None:
            missing.append("speed_limit_kmh")
        return missing

    def can_confirm(self) -> bool:
        return self.is_intersection and self.is_supported_for_generation and not self.missing_fields()

    def recommended_lane_count(self) -> int:
        fallback = 2
        if self.topology in SUPPORTED_TOPOLOGIES:
            return self.directional_lanes.effective_lane_count(self.topology, fallback)
        return fallback

    def to_generate_arguments(self, should_run_simulation: bool = False) -> dict[str, Any]:
        lane_count = self.recommended_lane_count()
        args: dict[str, Any] = {"scenario_type": self.topology, "lane_count": lane_count, "directional_lanes": self.directional_lanes.merged_with_fallback(self.topology, lane_count).model_dump(exclude_none=True), "should_run_simulation": should_run_simulation}
        if self.road_length_m is not None:
            args["road_length"] = float(self.road_length_m)
        if self.speed_limit_kmh is not None:
            args["speed_limit_kmh"] = float(self.speed_limit_kmh)
        return args


class ImageAnalysisResult(BaseModel):
    status: ImageAnalysisStatus
    reply_text: str
    draft: IntersectionImageDraft | None = None
    issues: list[str] = Field(default_factory=list)
    assistant_name: str = ASSISTANT_NAME
    allow_confirm: bool = False
    allow_customize: bool = False
    allow_reupload: bool = False
