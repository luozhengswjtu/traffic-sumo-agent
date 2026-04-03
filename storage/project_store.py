from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from storage.path_utils import normalize_local_path
from sumo_domain.project_spec import ProjectMeta


class ProjectStore:
    """Manage project directories and their metadata files."""

    META_FILENAME = "project.json"

    def __init__(self, base_projects_dir: Path) -> None:
        self.base_projects_dir = normalize_local_path(base_projects_dir)
        self.base_projects_dir.mkdir(parents=True, exist_ok=True)

    def create_project(self, name: str, base_dir: Path | None = None) -> ProjectMeta:
        root_dir = normalize_local_path(base_dir or self.base_projects_dir)
        root_dir.mkdir(parents=True, exist_ok=True)

        project_dir = normalize_local_path(root_dir / self._sanitize_name(name))
        project_dir.mkdir(parents=True, exist_ok=True)

        for folder_name in ("sumo", "logs", "outputs"):
            (project_dir / folder_name).mkdir(parents=True, exist_ok=True)

        now = datetime.now()
        meta = ProjectMeta(
            name=name,
            project_dir=project_dir,
            created_at=now,
            updated_at=now,
        )
        self.save_project_meta(meta)
        return meta

    def open_project(self, path: Path) -> ProjectMeta:
        return self.load_project_meta(path)

    def save_project_meta(self, meta: ProjectMeta) -> None:
        project_dir = normalize_local_path(meta.project_dir)
        normalized_meta = meta.model_copy(update={"project_dir": project_dir})
        project_dir.mkdir(parents=True, exist_ok=True)
        meta_path = project_dir / self.META_FILENAME
        payload = normalized_meta.model_dump(mode="json")
        meta_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def load_project_meta(self, path: Path) -> ProjectMeta:
        project_dir = normalize_local_path(path)
        meta_path = project_dir / self.META_FILENAME
        if not meta_path.exists():
            raise FileNotFoundError(f"未找到项目元数据文件: {meta_path}")
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        meta = ProjectMeta.model_validate(data)
        normalized_dir = normalize_local_path(meta.project_dir)
        if str(meta.project_dir) != str(normalized_dir):
            meta = meta.model_copy(update={"project_dir": normalized_dir})
            self.save_project_meta(meta)
        return meta

    def list_project_files(self, path: Path) -> list[Path]:
        project_dir = normalize_local_path(path)
        if not project_dir.exists():
            return []
        return [item for item in project_dir.rglob("*") if item.is_file()]

    @staticmethod
    def _sanitize_name(name: str) -> str:
        cleaned = re.sub(r'[<>:"/\\|?*]+', "_", name).strip()
        return cleaned or "traffic_agent_project"
