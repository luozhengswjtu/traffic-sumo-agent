from __future__ import annotations

from pydantic import BaseModel

from sumo_domain.network_spec import EdgeSpec, NetworkSpec, NodeSpec


class NetworkGenerationRequest(BaseModel):
    scenario_type: str = "intersection"
    lane_count: int = 2
    road_length: float = 200.0
    speed_limit: float = 13.89
    node_type: str = "priority"


class NetworkGenerator:
    """Create simple template-based network definitions for MVP scenarios."""

    def generate(self, request: NetworkGenerationRequest) -> NetworkSpec:
        scenario_type = request.scenario_type.lower().strip()
        if scenario_type in {"intersection", "cross", "crossroad"}:
            return self.generate_intersection(request)
        if scenario_type in {"t_junction", "t-junction", "tjunction", "t"}:
            return self.generate_t_junction(request)
        if scenario_type in {"corridor", "straight", "road"}:
            return self.generate_corridor(request)
        raise ValueError(f"暂不支持的场景类型: {request.scenario_type}")

    def generate_intersection(self, spec: NetworkGenerationRequest) -> NetworkSpec:
        half = spec.road_length / 2.0
        nodes = [
            NodeSpec(id="center", x=0.0, y=0.0, type=spec.node_type),
            NodeSpec(id="north", x=0.0, y=half, type=spec.node_type),
            NodeSpec(id="south", x=0.0, y=-half, type=spec.node_type),
            NodeSpec(id="west", x=-half, y=0.0, type=spec.node_type),
            NodeSpec(id="east", x=half, y=0.0, type=spec.node_type),
        ]
        edges = [
            self._edge("north_in", "north", "center", spec),
            self._edge("north_out", "center", "north", spec),
            self._edge("south_in", "south", "center", spec),
            self._edge("south_out", "center", "south", spec),
            self._edge("west_in", "west", "center", spec),
            self._edge("west_out", "center", "west", spec),
            self._edge("east_in", "east", "center", spec),
            self._edge("east_out", "center", "east", spec),
        ]
        return NetworkSpec(scenario_type="intersection", nodes=nodes, edges=edges)

    def generate_t_junction(self, spec: NetworkGenerationRequest) -> NetworkSpec:
        half = spec.road_length / 2.0
        nodes = [
            NodeSpec(id="center", x=0.0, y=0.0, type=spec.node_type),
            NodeSpec(id="north", x=0.0, y=half, type=spec.node_type),
            NodeSpec(id="west", x=-half, y=0.0, type=spec.node_type),
            NodeSpec(id="east", x=half, y=0.0, type=spec.node_type),
        ]
        edges = [
            self._edge("north_in", "north", "center", spec),
            self._edge("north_out", "center", "north", spec),
            self._edge("west_in", "west", "center", spec),
            self._edge("west_out", "center", "west", spec),
            self._edge("east_in", "east", "center", spec),
            self._edge("east_out", "center", "east", spec),
        ]
        return NetworkSpec(scenario_type="t_junction", nodes=nodes, edges=edges)

    def generate_corridor(self, spec: NetworkGenerationRequest) -> NetworkSpec:
        half = spec.road_length / 2.0
        nodes = [
            NodeSpec(id="center", x=0.0, y=0.0, type=spec.node_type),
            NodeSpec(id="west", x=-half, y=0.0, type=spec.node_type),
            NodeSpec(id="east", x=half, y=0.0, type=spec.node_type),
        ]
        edges = [
            self._edge("west_in", "west", "center", spec),
            self._edge("west_out", "center", "west", spec),
            self._edge("east_in", "east", "center", spec),
            self._edge("east_out", "center", "east", spec),
        ]
        return NetworkSpec(scenario_type="corridor", nodes=nodes, edges=edges)

    @staticmethod
    def _edge(edge_id: str, from_node: str, to_node: str, spec: NetworkGenerationRequest) -> EdgeSpec:
        return EdgeSpec(
            id=edge_id,
            from_node=from_node,
            to_node=to_node,
            num_lanes=spec.lane_count,
            speed=spec.speed_limit,
            length=spec.road_length / 2.0,
        )
