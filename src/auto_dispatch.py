from __future__ import annotations

from typing import Any

from .config import now_str
from .db import db_conn, init_db
from contextlib import closing

TASK_TYPE_ROUTING: dict[str, str] = {
    "requirement": "Gemini CLI",
    "architecture": "Claude Code",
    "development": "Codex",
    "testing": "Codex",
    "deployment": "Hermes",
}


def auto_dispatch_task(task: dict[str, Any]) -> dict[str, Any]:
    """根据任务类型自动推荐 AI 工具"""
    tool = TASK_TYPE_ROUTING.get(task.get("task_type", ""))
    if not tool:
        return {"dispatched": False, "reason": "no matching tool"}
    return {"dispatched": True, "tool": tool, "task_id": task.get("id")}


def get_dispatched_tasks() -> list[dict[str, Any]]:
    init_db()
    with closing(db_conn()) as conn:
        rows = conn.execute(
            "SELECT * FROM tasks WHERE dispatched_tool IS NOT NULL ORDER BY updated_at DESC LIMIT 20"
        ).fetchall()
    return [dict(r) for r in rows]
