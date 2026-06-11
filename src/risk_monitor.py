from __future__ import annotations

import sqlite3
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import DB_PATH
from .subscription_reminders import get_subscription_expiry_risks
from .tool_health import get_tool_health_status

PROJECTS_TO_MONITOR = {
    "ccec-timer-system": Path.home() / "company" / "ccec-timer-system",
    "edge-caculate-box": Path.home() / "company" / "edge-caculate-box",
}


def check_project_stalls() -> list[dict[str, Any]]:
    risks: list[dict[str, Any]] = []
    for name, path in PROJECTS_TO_MONITOR.items():
        if not path.exists():
            continue
        try:
            result = subprocess.run(
                ["git", "-C", str(path), "log", "--oneline", "-1", "--format=%ct"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=5,
            )
        except Exception as exc:
            risks.append(
                {
                    "type": "project_git_check_failed",
                    "level": "warning",
                    "project": name,
                    "path": str(path),
                    "message": f"{name} Git 活跃度检查失败：{exc}",
                }
            )
            continue

        last_ts_text = result.stdout.strip()
        if not last_ts_text:
            continue
        last = datetime.fromtimestamp(int(last_ts_text))
        days_since = (datetime.now() - last).days
        if days_since >= 3:
            risks.append(
                {
                    "type": "project_stall",
                    "level": "high",
                    "project": name,
                    "path": str(path),
                    "days": days_since,
                    "last_commit_at": last.isoformat(timespec="seconds"),
                    "message": f"{name} 已 {days_since} 天无 Git 提交",
                }
            )
    return risks


def check_overdue_tasks(db_path: str = DB_PATH) -> list[dict[str, Any]]:
    risks: list[dict[str, Any]] = []
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT id, title, project, due_at, status, priority
                FROM tasks
                WHERE due_at IS NOT NULL
                  AND due_at < datetime('now')
                  AND status != '已完成'
                ORDER BY due_at ASC
                """
            ).fetchall()
    except Exception:
        return risks

    for row in rows:
        risks.append(
            {
                "type": "task_overdue",
                "level": "high" if row["priority"] == "P0" else "warning",
                "task_id": row["id"],
                "title": row["title"],
                "project": row["project"],
                "due_at": row["due_at"],
                "status": row["status"],
                "priority": row["priority"],
                "message": f"任务 #{row['id']} 已超期：{row['title']}",
            }
        )
    return risks


def check_tool_health() -> list[dict[str, Any]]:
    """从 SQLite 读取工具健康状态，返回 degraded 风险项"""
    risks = []
    for t in get_tool_health_status():
        if t.get("status") and t["status"] != "ok":
            risks.append({
                "type": "tool_degraded",
                "level": t.get("level", "warning"),
                "tool": t["tool"],
                "status": t["status"],
                "last_known_ok": t.get("last_ok_at"),
                "message": t.get("last_error") or f"{t['tool']} 状态异常 ({t['status']})",
                "suggestion": t.get("suggestion", ""),
            })
    return risks


def get_all_risks() -> list[dict[str, Any]]:
    return (
        check_project_stalls()
        + check_overdue_tasks(DB_PATH)
        + check_tool_health()
        + get_subscription_expiry_risks(7)
    )
