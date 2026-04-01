from __future__ import annotations

import json
from pathlib import Path

from sumo_domain.project_spec import RecentProjectItem


class RecentProjectStore:
    """Persist a short list of recently opened projects."""

    def __init__(self, file_path: Path, max_items: int = 10) -> None:
        self.file_path = file_path
        self.max_items = max_items
        self.file_path.parent.mkdir(parents=True, exist_ok=True)

    def list_recent_projects(self) -> list[RecentProjectItem]:
        if not self.file_path.exists():
            return []
        data = json.loads(self.file_path.read_text(encoding="utf-8"))
        return [RecentProjectItem.model_validate(item) for item in data]

    def add_recent_project(self, item: RecentProjectItem) -> None:
        items = [entry for entry in self.list_recent_projects() if entry.project_dir != item.project_dir]
        items.insert(0, item)
        self._save(items[: self.max_items])

    def remove_recent_project(self, path: Path) -> None:
        target = str(path.resolve())
        items = [entry for entry in self.list_recent_projects() if entry.project_dir != target]
        self._save(items)

    def _save(self, items: list[RecentProjectItem]) -> None:
        payload = [item.model_dump(mode="json") for item in items]
        self.file_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
