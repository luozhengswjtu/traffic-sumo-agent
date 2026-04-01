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

        net_file = sumo_dir / "scenario.net.xml"
        if net_file.exists() and self._is_placeholder_net(net_file):
            issues.append(
                ValidationIssue(
                    level="warning",
                    message="当前 net.xml 是占位文件，说明本机还没有可用的 netconvert。",
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

    @staticmethod
    def _is_placeholder_net(path: Path) -> bool:
        try:
            root = ET.parse(path).getroot()
        except ET.ParseError:
            return False
        return root.attrib.get("placeholder") == "true"
