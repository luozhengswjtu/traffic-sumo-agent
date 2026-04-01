from __future__ import annotations

import sqlite3
from pathlib import Path

_DB_PATH: Path | None = None


def init_db(db_path: Path) -> None:
    global _DB_PATH
    _DB_PATH = db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS session_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                role TEXT NOT NULL,
                message TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS project_operation_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                project_name TEXT,
                project_dir TEXT,
                intent TEXT NOT NULL,
                user_message TEXT NOT NULL,
                change_summary TEXT NOT NULL,
                before_state TEXT,
                after_state TEXT,
                generated_files TEXT NOT NULL,
                issues TEXT NOT NULL
            )
            """
        )
        connection.commit()


def get_connection() -> sqlite3.Connection:
    if _DB_PATH is None:
        raise RuntimeError("数据库尚未初始化，请先调用 init_db().")
    return sqlite3.connect(_DB_PATH)
