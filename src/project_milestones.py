from __future__ import annotations

import sqlite3
from contextlib import closing
from typing import Any

from .config import now_str
from .db import db_conn, init_db

MILESTONE_SCHEMA = """
CREATE TABLE IF NOT EXISTS project_milestones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project TEXT NOT NULL,
    name TEXT NOT NULL,
    due_date TEXT,
    status TEXT DEFAULT 'pending',
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);
"""


def init_milestones_table():
    init_db()
    with closing(db_conn()) as conn:
        conn.execute(MILESTONE_SCHEMA)
        conn.commit()


def list_milestones(project: str) -> list[dict[str, Any]]:
    init_milestones_table()
    with closing(db_conn()) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM project_milestones WHERE project = ? ORDER BY due_date ASC, id ASC",
            (project,),
        ).fetchall()
    return [dict(r) for r in rows]


def create_milestone(project: str, name: str, due_date: str | None = None) -> dict[str, Any]:
    init_milestones_table()
    ts = now_str()
    with closing(db_conn()) as conn:
        cur = conn.execute(
            "INSERT INTO project_milestones (project, name, due_date, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (project, name, due_date, ts, ts),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM project_milestones WHERE id = ?", (cur.lastrowid,)).fetchone()
    return dict(row)


def update_milestone(mid: int, status: str) -> dict[str, Any] | None:
    init_milestones_table()
    ts = now_str()
    with closing(db_conn()) as conn:
        conn.execute(
            "UPDATE project_milestones SET status = ?, updated_at = ? WHERE id = ?",
            (status, ts, mid),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM project_milestones WHERE id = ?", (mid,)).fetchone()
    return dict(row) if row else None


def milestone_summary(project: str) -> dict[str, Any]:
    milestones = list_milestones(project)
    total = len(milestones)
    done = sum(1 for m in milestones if m["status"] == "done")
    return {"total": total, "done": done, "progress": f"{done}/{total}" if total > 0 else "0/0"}
