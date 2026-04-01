from __future__ import annotations

from pydantic import BaseModel

from sumo_domain.network_spec import NetworkSpec
from sumo_domain.route_spec import FlowSpec, RouteSpec


class RouteGenerationRequest(BaseModel):
    flow_level: str = "medium"
    flow_rate: int | None = None
    flow_multiplier: float | None = None
    duration_seconds: int = 1800
    traffic_bias: str | None = None


class RouteGenerator:
    """Create simple origin-destination flow definitions for generated templates."""

    FLOW_LEVEL_MAP = {
        "low": 300,
        "medium": 600,
        "high": 1200,
        "very_high": 1800,
    }

    OPPOSITE_EDGE_MAP = {
        "north_in": "south_out",
        "south_in": "north_out",
        "west_in": "east_out",
        "east_in": "west_out",
    }

    def generate_routes(self, network: NetworkSpec, request: RouteGenerationRequest) -> RouteSpec:
        base_rate = request.flow_rate or self.FLOW_LEVEL_MAP.get(request.flow_level.lower(), self.FLOW_LEVEL_MAP["medium"])
        if request.flow_multiplier is not None:
            base_rate = max(1, int(round(base_rate * request.flow_multiplier)))

        incoming_edges = [edge.id for edge in network.edges if edge.id.endswith("_in")]
        available_edges = {edge.id for edge in network.edges}

        flows: list[FlowSpec] = []
        for index, incoming in enumerate(incoming_edges, start=1):
            outgoing = self.OPPOSITE_EDGE_MAP.get(incoming)
            if outgoing not in available_edges:
                continue
            flows.append(
                FlowSpec(
                    id=f"flow_{index}",
                    from_edge=incoming,
                    to_edge=outgoing,
                    begin=0,
                    end=request.duration_seconds,
                    vehs_per_hour=self._apply_bias(incoming, base_rate, request.traffic_bias),
                )
            )

        return RouteSpec(flows=flows)

    @staticmethod
    def _apply_bias(incoming_edge: str, base_rate: int, traffic_bias: str | None) -> int:
        if not traffic_bias:
            return base_rate

        bias = traffic_bias.lower().strip()
        if bias in {"ns", "north_south"} and incoming_edge in {"north_in", "south_in"}:
            return int(round(base_rate * 1.3))
        if bias in {"ew", "east_west"} and incoming_edge in {"east_in", "west_in"}:
            return int(round(base_rate * 1.3))
        return base_rate
