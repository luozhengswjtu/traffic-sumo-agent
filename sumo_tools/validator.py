from __future__ import annotations

from pathlib import Path
import xml.etree.ElementTree as ET

from pydantic import BaseModel, Field

from sumo_domain.project_spec import ProjectContext


class ValidationIssue(BaseModel):
    level: str
    message: str
    file: str | None = None


class BuildResult(BaseModel):
    generated_files: list[Path] = Field(default_factory=list)
    issues: list[ValidationIssue] = Field(default_factory=list)


class SumoProjectValidator:
    REQUIRED_FILES = [
        "scenario.nod.xml",
        "scenario.edg.xml",
        "scenario.rou.xml",
        "scenario.net.xml",
        "scenario.sumocfg",
    ]

    def validate_project(self, project_dir: Path) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        sumo_dir = project_dir / "sumo"

        for filename in self.REQUIRED_FILES:
            file_path = sumo_dir / filename
            if not file_path.exists():
                issues.append(
                    ValidationIssue(level="error", message=f"缺少文件: {filename}", file=str(file_path))
                )

        sumocfg_path = sumo_dir / "scenario.sumocfg"
        if sumocfg_path.exists():
            issues.extend(self._validate_sumocfg(sumocfg_path))

        net_file = sumo_dir / "scenario.net.xml"
        if net_file.exists() and self._is_placeholder_net(net_file):
            issues.append(
                ValidationIssue(
                    level="error",
                    message="当前 net.xml 是占位文件，无法运行仿真，请检查 netconvert 是否可用。",
                    file=str(net_file),
                )
            )

        return issues

    def validate_context(self, context: ProjectContext) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []

        if context.network is None:
            issues.append(ValidationIssue(level="error", message="ProjectContext 缺少 network。"))
        else:
            if not context.network.nodes:
                issues.append(ValidationIssue(level="error", message="NetworkSpec 没有节点。"))
            if not context.network.edges:
                issues.append(ValidationIssue(level="error", message="NetworkSpec 没有边。"))

        if context.routes is None:
            issues.append(ValidationIssue(level="error", message="ProjectContext 缺少 routes。"))
        else:
            if not context.routes.flows:
                issues.append(ValidationIssue(level="warning", message="RouteSpec 当前没有 flow。"))

        if context.simulation is None:
            issues.append(ValidationIssue(level="error", message="ProjectContext 缺少 simulation。"))

        return issues

    def assert_runnable(self, project_dir: Path) -> None:
        issues = self.validate_project(project_dir)
        errors = [issue for issue in issues if issue.level == "error"]
        if errors:
            joined = "；".join(issue.message for issue in errors)
            raise RuntimeError(f"SUMO 项目不可运行: {joined}")

    def _validate_sumocfg(self, sumocfg_path: Path) -> list[ValidationIssue]:
        try:
            root = ET.parse(sumocfg_path).getroot()
        except ET.ParseError as exc:
            return [
                ValidationIssue(
                    level="error",
                    message=f"scenario.sumocfg 不是合法 XML: {exc}",
                    file=str(sumocfg_path),
                )
            ]

        issues: list[ValidationIssue] = []
        input_section = root.find("input")
        if input_section is None:
            issues.append(
                ValidationIssue(level="error", message="scenario.sumocfg 缺少 <input> 节点。", file=str(sumocfg_path))
            )
        else:
            issues.extend(self._validate_input_reference(sumocfg_path, input_section, "net-file"))
            issues.extend(self._validate_input_reference(sumocfg_path, input_section, "route-files"))

        time_section = root.find("time")
        if time_section is None:
            issues.append(
                ValidationIssue(level="error", message="scenario.sumocfg 缺少 <time> 节点。", file=str(sumocfg_path))
            )
        else:
            issues.extend(self._validate_step_length(sumocfg_path, time_section))

        return issues

    def _validate_input_reference(self, sumocfg_path: Path, input_section: ET.Element, tag: str) -> list[ValidationIssue]:
        element = input_section.find(tag)
        if element is None:
            return [ValidationIssue(level="error", message=f"scenario.sumocfg 缺少 <{tag}> 配置。", file=str(sumocfg_path))]

        raw_value = (element.attrib.get("value") or "").strip()
        if not raw_value:
            return [ValidationIssue(level="error", message=f"scenario.sumocfg 的 <{tag}> 没有 value。", file=str(sumocfg_path))]

        refs = [item.strip() for item in raw_value.split(",") if item.strip()]
        if not refs:
            return [ValidationIssue(level="error", message=f"scenario.sumocfg 的 <{tag}> 引用为空。", file=str(sumocfg_path))]

        issues: list[ValidationIssue] = []
        for ref in refs:
            ref_path = Path(ref)
            resolved = ref_path if ref_path.is_absolute() else (sumocfg_path.parent / ref_path).resolve()
            if not resolved.exists():
                issues.append(
                    ValidationIssue(
                        level="error",
                        message=f"scenario.sumocfg 引用的 {tag} 文件不存在: {ref}",
                        file=str(sumocfg_path),
                    )
                )
        return issues

    def _validate_step_length(self, sumocfg_path: Path, time_section: ET.Element) -> list[ValidationIssue]:
        element = time_section.find("step-length")
        if element is None:
            return []

        raw_value = (element.attrib.get("value") or "").strip()
        if not raw_value:
            return [ValidationIssue(level="error", message="scenario.sumocfg 的 step-length 为空。", file=str(sumocfg_path))]

        try:
            step_length = float(raw_value)
        except ValueError:
            return [
                ValidationIssue(
                    level="error",
                    message=f"scenario.sumocfg 的 step-length 不是数字: {raw_value}",
                    file=str(sumocfg_path),
                )
            ]

        if step_length <= 0:
            return [
                ValidationIssue(
                    level="error",
                    message=f"scenario.sumocfg 的 step-length 必须大于 0: {raw_value}",
                    file=str(sumocfg_path),
                )
            ]
        return []

    @staticmethod
    def _is_placeholder_net(path: Path) -> bool:
        try:
            root = ET.parse(path).getroot()
        except ET.ParseError:
            return False
        return root.attrib.get("placeholder") == "true"
