from __future__ import annotations

import os
import json
import re
import shutil
import sqlite3
import subprocess
import threading
import time
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .config import *
from .db import db_conn
from .dispatch import latest_task_log_path, log_indicates_success, read_file_tail

def get_task_counts(conn: sqlite3.Connection) -> dict:
    rows = conn.execute(
        """
        SELECT status, COUNT(*) AS cnt
        FROM tasks
        GROUP BY status
        """
    ).fetchall()
    base = {"待分配": 0, "AI执行中": 0, "待人工审查": 0, "已完成": 0}
    for r in rows:
        base[r["status"]] = r["cnt"]
    return base


def get_overdue_tasks(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT *
        FROM tasks
        WHERE due_at IS NOT NULL
          AND due_at < ?
          AND status != '已完成'
        ORDER BY due_at ASC
        """,
        (now_str(),),
    ).fetchall()


def get_due_soon_tasks(conn: sqlite3.Connection, minutes: int = 60) -> list[sqlite3.Row]:
    end = datetime.now() + timedelta(minutes=minutes)
    return conn.execute(
        """
        SELECT *
        FROM tasks
        WHERE due_at IS NOT NULL
          AND due_at >= ?
          AND due_at <= ?
          AND status != '已完成'
        ORDER BY due_at ASC
        """,
        (now_str(), end.strftime("%Y-%m-%d %H:%M:%S")),
    ).fetchall()


def reconcile_task_statuses(conn: sqlite3.Connection) -> None:
    ts = now_str()
    timeout_seconds = get_dispatch_timeout_seconds()
    stale_rows = conn.execute(
        """
        SELECT id, execution_started_at, execution_progress
        FROM tasks
        WHERE execution_state = 'running'
          AND execution_finished_at IS NULL
          AND execution_started_at IS NOT NULL
        """
    ).fetchall()
    for row in stale_rows:
        started_at = parse_datetime_value(row["execution_started_at"])
        if not started_at or (datetime.now() - started_at).total_seconds() <= timeout_seconds:
            continue
        log_path = latest_task_log_path(row["id"])
        log_tail = read_file_tail(log_path, max_chars=12000) if log_path else ""
        old_progress = (row["execution_progress"] or "").strip()
        if log_indicates_success(log_tail):
            line = f"[{ts}] 检测到孤儿执行已完成：后台监控中断，但日志包含成功结束信号，自动推进到待人工审查。"
            progress = f"{old_progress}\n{line}".strip() if old_progress else line
            conn.execute(
                """
                UPDATE tasks
                SET execution_state = 'succeeded',
                    status = '待人工审查',
                    execution_output = ?,
                    execution_error = NULL,
                    execution_finished_at = ?,
                    execution_progress = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (log_tail, ts, progress[-8000:], ts, row["id"]),
            )
        else:
            source = f"，日志文件：{log_path}" if log_path else ""
            line = f"[{ts}] 检测到孤儿执行超时：后台监控中断且已超过 {timeout_seconds} 秒，自动回退待处理。"
            progress = f"{old_progress}\n{line}".strip() if old_progress else line
            conn.execute(
                """
                UPDATE tasks
                SET execution_state = 'failed',
                    status = '待分配',
                    execution_output = ?,
                    execution_error = ?,
                    execution_finished_at = ?,
                    execution_progress = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    log_tail,
                    f"执行监控中断或超时（超过 {timeout_seconds} 秒）{source}",
                    ts,
                    progress[-8000:],
                    ts,
                    row["id"],
                ),
            )
    conn.execute(
        """
        UPDATE tasks
        SET status = '待人工审查', updated_at = ?
        WHERE execution_state = 'succeeded'
          AND status = 'AI执行中'
        """,
        (ts,),
    )
    conn.execute(
        """
        UPDATE tasks
        SET status = '已完成', updated_at = ?
        WHERE execution_state = 'succeeded'
          AND review_result = 'approved'
          AND status != '已完成'
        """,
        (ts,),
    )
    conn.execute(
        """
        UPDATE tasks
        SET status = '待分配', updated_at = ?
        WHERE execution_state IN ('failed', 'unsupported')
          AND status = 'AI执行中'
        """,
        (ts,),
    )


def row_to_task(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "title": row["title"],
        "project": row["project"],
        "assignee_ai": row["assignee_ai"],
        "status": row["status"],
        "priority": row["priority"],
        "due_at": row["due_at"],
        "estimated_finish_at": row["estimated_finish_at"],
        "acceptance_criteria": row["acceptance_criteria"],
        "notes": row["notes"],
        "execution_state": row["execution_state"],
        "execution_tool": row["execution_tool"],
        "execution_command": row["execution_command"],
        "execution_output": row["execution_output"],
        "execution_error": row["execution_error"],
        "execution_progress": row["execution_progress"],
        "execution_started_at": row["execution_started_at"],
        "execution_finished_at": row["execution_finished_at"],
        "review_result": row["review_result"],
        "review_comment": row["review_comment"],
        "reviewed_at": row["reviewed_at"],
        "task_type": row["task_type"] or "fullstack",
        "ai_instruction": row["ai_instruction"],
        "locked_scope": row["locked_scope"],
        "expected_output": row["expected_output"],
        "verification_command": row["verification_command"],
        "routing_reason": row["routing_reason"],
        "delivery_evidence": row["delivery_evidence"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def build_task_execution_report(task: dict[str, Any]) -> dict[str, Any]:
    progress = task.get("execution_progress") or ""
    output = task.get("execution_output") or ""
    error = task.get("execution_error") or ""
    routing = task.get("routing_reason") or ""
    command = task.get("execution_command") or ""
    is_succeeded = task.get("execution_state") == "succeeded"
    is_reviewed = task.get("review_result") == "approved"
    is_auto_executed = bool(task.get("execution_started_at") and task.get("execution_finished_at"))
    is_fully_automatic = is_succeeded and not task.get("review_result")
    automation_level = "执行自动化，审查人工确认" if is_reviewed else ("执行自动化" if is_succeeded else "未完成自动化闭环")

    evidence_lines = []
    for line in progress.splitlines():
        if any(key in line for key in ["可执行候选链路", "跳过不可用节点", "故障转移", "开始执行", "进程已启动", "执行完成", "人工审查"]):
            evidence_lines.append(line)
    if error:
        evidence_lines.append(f"执行错误：{error}")

    markdown = "\n".join(
        [
            f"# 任务执行报告：{task['title']}",
            "",
            f"- 任务 ID：{task['id']}",
            f"- 项目：{task['project']}",
            f"- 任务类型：{task.get('task_type') or 'fullstack'}",
            f"- 执行工具：{task.get('execution_tool') or task.get('assignee_ai')}",
            f"- 状态：{task['status']} / {task['execution_state']}",
            f"- 开始时间：{task.get('execution_started_at') or '-'}",
            f"- 结束时间：{task.get('execution_finished_at') or '-'}",
            f"- 自动化结论：{automation_level}",
            "",
            "## 路由依据",
            "",
            routing or "未记录路由原因。",
            "",
            "## 执行证据",
            "",
            "\n".join(f"- {line}" for line in evidence_lines) if evidence_lines else "暂无执行证据。",
            "",
            "## 最终输出摘要",
            "",
            output[-4000:] if output else "暂无执行输出。",
            "",
            "## 结论",
            "",
            "该任务已完成自动执行，并经过人工审查确认。" if is_reviewed else (
                "该任务已完成自动执行，等待人工审查。" if is_succeeded else "该任务尚未完成成功闭环。"
            ),
        ]
    )

    return {
        "task_id": task["id"],
        "title": task["title"],
        "project": task["project"],
        "status": task["status"],
        "execution_state": task["execution_state"],
        "automation": {
            "auto_executed": is_auto_executed,
            "auto_routed": "Token 优先链路" in routing,
            "auto_context_injected": "Context injected" in output or "acp-agent" in command,
            "auto_logged": bool(progress),
            "human_review_required": bool(task.get("review_result")),
            "fully_automatic": is_fully_automatic,
            "level": automation_level,
        },
        "evidence": evidence_lines,
        "markdown": markdown,
    }


def row_to_decision(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "project": row["project"],
        "decision": row["decision"],
        "context": row["context"],
        "reason": row["reason"],
        "impact": row["impact"],
        "created_at": row["created_at"],
    }


def fetch_tasks(conn: sqlite3.Connection, filters: dict[str, str] | None = None) -> list[sqlite3.Row]:
    filters = filters or {}
    where: list[str] = []
    args: list[Any] = []

    q = filters.get("q", "").strip()
    if q:
        where.append("(title LIKE ? OR project LIKE ? OR notes LIKE ? OR acceptance_criteria LIKE ?)")
        like_q = f"%{q}%"
        args.extend([like_q, like_q, like_q, like_q])

    project = filters.get("project", "").strip()
    if project:
        where.append("project = ?")
        args.append(project)

    status = filters.get("status", "").strip()
    if status:
        where.append("status = ?")
        args.append(status)

    priority = filters.get("priority", "").strip()
    if priority:
        where.append("priority = ?")
        args.append(priority)

    execution_state = filters.get("execution_state", "").strip()
    if execution_state:
        where.append("execution_state = ?")
        args.append(execution_state)

    sql = "SELECT * FROM tasks"
    if where:
        sql += " WHERE " + " AND ".join(where)
    order_by = filters.get("order_by", "updated_at").strip()
    order_sql = {
        "updated_at": "updated_at DESC, created_at DESC",
        "created_at": "created_at DESC",
        "due_at": "due_at IS NULL, due_at ASC, priority ASC",
        "priority": "CASE priority WHEN 'P0' THEN 0 WHEN 'P1' THEN 1 ELSE 2 END, updated_at DESC",
    }.get(order_by, "updated_at DESC, created_at DESC")
    sql += f" ORDER BY {order_sql}"
    return conn.execute(sql, args).fetchall()
