from __future__ import annotations

from pathlib import Path
import xml.etree.ElementTree as ET

from storage.path_utils import normalize_local_path
from sumo_domain.network_spec import NetworkSpec
from sumo_domain.project_spec import ProjectContext
from sumo_domain.route_spec import RouteSpec
from sumo_domain.simulation_spec import SimulationSpec
from sumo_tools.config_generator import ConfigGenerator
from sumo_tools.netconvert_service import NetconvertService
from sumo_tools.validator import BuildResult, SumoProjectValidator, ValidationIssue


class ProjectBuilder:
    """Persist a ProjectContext into a SUMO-oriented project workspace."""

    OUTPUT_FILENAMES = (
        "scenario.nod.xml",
        "scenario.edg.xml",
        "scenario.rou.xml",
        "scenario.net.xml",
        "scenario.sumocfg",
    )

    def __init__(
        self,
        config_generator: ConfigGenerator | None = None,
        netconvert_service: NetconvertService | None = None,
        validator: SumoProjectValidator | None = None,
    ) -> None:
        self.config_generator = config_generator or ConfigGenerator()
        self.netconvert_service = netconvert_service or NetconvertService()
        self.validator = validator or SumoProjectValidator()

    def build_project(self, context: ProjectContext) -> BuildResult:
        issues = self.validator.validate_context(context)
        generated_files: list[Path] = []

        if context.network is None or context.routes is None or context.simulation is None:
            return BuildResult(generated_files=generated_files, issues=issues)

        project_dir = normalize_local_path(context.meta.project_dir)
        self._clear_previous_outputs(project_dir)

        try:
            node_file, edge_file = self.write_network_files(project_dir, context.network)
            generated_files.extend([node_file, edge_file])

            route_file = self.write_route_files(project_dir, context.routes)
            generated_files.append(route_file)

            net_file = self.netconvert_service.build_net_file(project_dir, node_file, edge_file)
            generated_files.append(net_file)

            config_file = self.write_config_file(project_dir, context.simulation)
            generated_files.append(config_file)
        except Exception as exc:
            issues.append(
                ValidationIssue(
                    level="error",
                    message=f"项目构建失败: {exc}",
                    file=str(project_dir / 'sumo'),
                )
            )
            return BuildResult(generated_files=generated_files, issues=issues)

        issues.extend(self.validator.validate_project(project_dir))
        return BuildResult(generated_files=generated_files, issues=issues)

    def write_network_files(self, project_dir: Path, network: NetworkSpec) -> tuple[Path, Path]:
        sumo_dir = normalize_local_path(project_dir / "sumo")
        sumo_dir.mkdir(parents=True, exist_ok=True)

        node_path = sumo_dir / "scenario.nod.xml"
        edge_path = sumo_dir / "scenario.edg.xml"

        node_root = ET.Element("nodes")
        for node in network.nodes:
            ET.SubElement(
                node_root,
                "node",
                id=node.id,
                x=f"{node.x:.2f}",
                y=f"{node.y:.2f}",
                type=node.type,
            )

        edge_root = ET.Element("edges")
        for edge in network.edges:
            attrs = {
                "id": edge.id,
                "from": edge.from_node,
                "to": edge.to_node,
                "numLanes": str(edge.num_lanes),
                "speed": f"{edge.speed:.2f}",
            }
            if edge.length is not None:
                attrs["length"] = f"{edge.length:.2f}"
            ET.SubElement(edge_root, "edge", **attrs)

        self._write_xml(node_path, node_root)
        self._write_xml(edge_path, edge_root)
        return node_path, edge_path

    def write_route_files(self, project_dir: Path, routes: RouteSpec) -> Path:
        sumo_dir = normalize_local_path(project_dir / "sumo")
        sumo_dir.mkdir(parents=True, exist_ok=True)

        route_path = sumo_dir / "scenario.rou.xml"
        root = ET.Element("routes")
        ET.SubElement(root, "vType", id="car", accel="2.6", decel="4.5", sigma="0.5", length="5.0")

        for flow in routes.flows:
            ET.SubElement(
                root,
                "flow",
                id=flow.id,
                begin=str(flow.begin),
                end=str(flow.end),
                **{
                    "from": flow.from_edge,
                    "to": flow.to_edge,
                    "vehsPerHour": str(flow.vehs_per_hour),
                    "type": "car",
                },
            )

        self._write_xml(route_path, root)
        return route_path

    def write_config_file(self, project_dir: Path, simulation: SimulationSpec) -> Path:
        sumo_dir = normalize_local_path(project_dir / "sumo")
        sumo_dir.mkdir(parents=True, exist_ok=True)
        config_path = sumo_dir / "scenario.sumocfg"
        return self.config_generator.write_sumocfg(config_path, simulation)

    def _clear_previous_outputs(self, project_dir: Path) -> None:
        sumo_dir = normalize_local_path(project_dir / "sumo")
        for filename in self.OUTPUT_FILENAMES:
            file_path = sumo_dir / filename
            if file_path.exists():
                file_path.unlink()

    @staticmethod
    def _write_xml(path: Path, root: ET.Element) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        ET.indent(root)
        ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)
