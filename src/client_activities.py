from __future__ import annotations

import sqlite3
from contextlib import closing
from typing import Any

from .config import now_str
from .db import db_conn, init_db

ACTIVITY_SCHEMA = """
CREATE TABLE IF NOT EXISTS client_activities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client TEXT NOT NULL,
    activity_type TEXT DEFAULT 'note',
    content TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
"""


def init_activities_table():
    init_db()
    with closing(db_conn()) as conn:
        conn.execute(ACTIVITY_SCHEMA)
        conn.commit()


def list_activities(client: str) -> list[dict[str, Any]]:
    init_activities_table()
    with closing(db_conn()) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM client_activities WHERE client = ? ORDER BY created_at DESC LIMIT 50",
            (client,),
        ).fetchall()
    return [dict(r) for r in rows]


def create_activity(client: str, activity_type: str, content: str) -> dict[str, Any]:
    init_activities_table()
    ts = now_str()
    with closing(db_conn()) as conn:
        cur = conn.execute(
            "INSERT INTO client_activities (client, activity_type, content, created_at) VALUES (?, ?, ?, ?)",
            (client, activity_type, content, ts),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM client_activities WHERE id = ?", (cur.lastrowid,)).fetchone()
    return dict(row)
