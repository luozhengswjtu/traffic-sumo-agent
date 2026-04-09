from __future__ import annotations

from pathlib import Path
import xml.etree.ElementTree as ET

from pydantic import BaseModel, Field

from sumo_domain.simulation_spec import SimulationSpec


class SimulationConfigRequest(BaseModel):
    duration_seconds: int = 1800
    step_length: float = 1.0
    seed: int | None = None
    begin_time: int = 0
    route_file: str = "scenario.rou.xml"
    net_file: str = "scenario.net.xml"
    additional_files: list[str] = Field(default_factory=list)


class ConfigGenerator:
    """Build and persist sumocfg configuration files."""

    def build_simulation_spec(self, project_dir: Path, request: SimulationConfigRequest) -> SimulationSpec:
        _ = project_dir
        return SimulationSpec(
            begin_time=request.begin_time,
            end_time=request.duration_seconds,
            step_length=request.step_length,
            seed=request.seed,
            route_file=request.route_file,
            net_file=request.net_file,
            additional_files=list(request.additional_files),
        )

    def write_sumocfg(self, path: Path, spec: SimulationSpec) -> Path:
        root = ET.Element("configuration")

        input_section = ET.SubElement(root, "input")
        ET.SubElement(input_section, "net-file", value=spec.net_file)
        ET.SubElement(input_section, "route-files", value=spec.route_file)
        if spec.additional_files:
            ET.SubElement(input_section, "additional-files", value=",".join(spec.additional_files))

        time_section = ET.SubElement(root, "time")
        ET.SubElement(time_section, "begin", value=str(spec.begin_time))
        ET.SubElement(time_section, "end", value=str(spec.end_time))
        ET.SubElement(time_section, "step-length", value=str(spec.step_length))

        if spec.seed is not None:
            random_section = ET.SubElement(root, "random_number")
            ET.SubElement(random_section, "seed", value=str(spec.seed))

        self._write_xml(path, root)
        return path

    @staticmethod
    def _write_xml(path: Path, root: ET.Element) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        ET.indent(root)
        tree = ET.ElementTree(root)
        tree.write(path, encoding="utf-8", xml_declaration=True)
