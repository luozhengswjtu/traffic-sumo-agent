from __future__ import annotations

import json
from pathlib import Path

from storage.db import get_connection
from sumo_domain.project_spec import ProjectOperationRecord


class ProjectHistoryStore:
    def add_record(self, record: ProjectOperationRecord) -> ProjectOperationRecord:
        with get_connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO project_operation_history (
                    created_at,
                    project_name,
                    project_dir,
                    intent,
                    user_message,
                    change_summary,
                    before_state,
                    after_state,
                    generated_files,
                    issues
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.created_at.isoformat(),
                    record.project_name,
                    record.project_dir,
                    record.intent,
                    record.user_message,
                    record.change_summary,
                    json.dumps(record.before_state, ensure_ascii=False) if record.before_state is not None else None,
                    json.dumps(record.after_state, ensure_ascii=False) if record.after_state is not None else None,
                    json.dumps(record.generated_files, ensure_ascii=False),
                    json.dumps(record.issues, ensure_ascii=False),
                ),
            )
            connection.commit()
            return record.model_copy(update={"id": int(cursor.lastrowid)})

    def list_recent(self, project_dir: str | Path | None = None, limit: int = 10) -> list[ProjectOperationRecord]:
        params: list[object] = []
        query = (
            "SELECT id, created_at, project_name, project_dir, intent, user_message, change_summary, before_state, after_state, generated_files, issues "
            "FROM project_operation_history "
        )
        if project_dir is not None:
            query += "WHERE project_dir = ? "
            params.append(str(project_dir))
        query += "ORDER BY id DESC LIMIT ?"
        params.append(max(1, limit))

        with get_connection() as connection:
            rows = connection.execute(query, params).fetchall()

        records: list[ProjectOperationRecord] = []
        for row in rows:
            records.append(
                ProjectOperationRecord(
                    id=row[0],
                    created_at=row[1],
                    project_name=row[2],
                    project_dir=row[3],
                    intent=row[4],
                    user_message=row[5],
                    change_summary=row[6],
                    before_state=json.loads(row[7]) if row[7] else None,
                    after_state=json.loads(row[8]) if row[8] else None,
                    generated_files=json.loads(row[9]) if row[9] else [],
                    issues=json.loads(row[10]) if row[10] else [],
                )
            )
        return records
