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

from flask import jsonify, render_template, request
from flask import Response

from .core import app
from .config import *
from .db import db_conn, init_db
from .dispatch import append_task_progress, dispatch_task_worker, launchd_service_status
from .projects import *
from .tasks import *
from .tools import *
from .tools import _TOOL_STATUS_CACHE

@app.route("/")
def dashboard() -> str:
    return render_template("dashboard.html")


@app.route("/api/projects")
def api_projects():
    company_dir, source = resolve_company_dir()
    projects = list_projects()
    warning = None
    if source == "safe_permission_denied":
        warning = "company 目录不可访问，请检查 ~/company 权限。"
    elif source == "desktop_permission_denied":
        warning = "服务进程没有 Desktop/company 访问权限，已回退或返回空列表。请给 python3/launchd 授权“桌面文件夹”或“完全磁盘访问”。"
    elif source == "unavailable":
        warning = "未找到可访问的项目目录（~/Desktop/company 或 ~/公司根目录）。"
    return jsonify(
        {
            "company_dir": str(company_dir),
            "projects": projects,
            "active_count": len(projects),
            "archived_count": len(list_archived_projects()),
            "archived_projects": list_archived_projects(),
            "source": source,
            "warning": warning,
            "pm_script": str(PM_SCRIPT),
        }
    )


@app.route("/api/projects", methods=["POST"])
def api_project_create():
    data = request.get_json(force=True, silent=False) or {}
    name = str(data.get("name", "")).strip()
    name_error = validate_project_name(name)
    if name_error:
        return jsonify({"error": name_error}), 400
    result = run_pm_command(["new", name])
    status = 200 if result.returncode == 0 else 400
    return jsonify({"ok": result.returncode == 0, "stdout": result.stdout, "stderr": result.stderr}), status


@app.route("/api/projects/<name>/archive", methods=["POST"])
def api_project_archive(name: str):
    name_error = validate_project_name(name)
    if name_error:
        return jsonify({"error": name_error}), 400
    result = run_pm_command(["archive", name])
    status = 200 if result.returncode == 0 else 400
    return jsonify({"ok": result.returncode == 0, "stdout": result.stdout, "stderr": result.stderr}), status


@app.route("/api/projects/<name>/unarchive", methods=["POST"])
def api_project_unarchive(name: str):
    name_error = validate_project_name(name)
    if name_error:
        return jsonify({"error": name_error}), 400
    result = run_pm_command(["unarchive", name])
    status = 200 if result.returncode == 0 else 400
    return jsonify({"ok": result.returncode == 0, "stdout": result.stdout, "stderr": result.stderr}), status


@app.route("/api/projects/<name>", methods=["DELETE"])
def api_project_delete(name: str):
    data = request.get_json(force=True, silent=True) or {}
    name_error = validate_project_name(name)
    if name_error:
        return jsonify({"error": name_error}), 400
    confirm_name = str(data.get("confirm_name", "")).strip()
    if confirm_name != name:
        return jsonify({"error": "confirm_name must match project name"}), 400
    result = run_pm_command(["delete", name], input_text=name + "\n")
    status = 200 if result.returncode == 0 else 400
    return jsonify({"ok": result.returncode == 0, "stdout": result.stdout, "stderr": result.stderr}), status


@app.route("/api/repositories")
def api_repositories():
    company_dir, source = resolve_company_dir()
    repos: list[dict[str, Any]] = []
    for project in list_projects():
        repos.extend(find_project_repositories(project))
    return jsonify(
        {
            "company_dir": str(company_dir),
            "source": source,
            "repositories": repos,
            "counts": {
                "total": len(repos),
                "git": sum(1 for repo in repos if repo["is_git"]),
                "dirty": sum(1 for repo in repos if repo["dirty"]),
                "not_git": sum(1 for repo in repos if not repo["is_git"]),
            },
        }
    )


@app.route("/api/repositories/action", methods=["POST"])
def api_repository_action():
    data = request.get_json(force=True, silent=True) or {}
    repo_path, error = resolve_repository_action_path(data.get("path"))
    if error:
        return jsonify({"error": error}), 400
    status, body = run_repository_action(repo_path, str(data.get("action", "")), data)
    return jsonify(body), status


def build_operations_report() -> dict[str, Any]:
    init_db()
    projects = list_projects()
    repos: list[dict[str, Any]] = []
    for project in projects:
        repos.extend(find_project_repositories(project))
    with closing(db_conn()) as conn:
        tasks = [row_to_task(r) for r in fetch_tasks(conn)]
        counts = get_task_counts(conn)
        decisions = [
            row_to_decision(r)
            for r in conn.execute("SELECT * FROM decision_logs ORDER BY created_at DESC LIMIT 20").fetchall()
        ]
    governance_avg = round(sum(p.get("governance_score", 0) for p in projects) / len(projects)) if projects else 0
    return {
        "generated_at": now_str(),
        "projects": {
            "total": len(projects),
            "archived": len(list_archived_projects()),
            "governance_avg": governance_avg,
            "items": projects,
        },
        "tasks": {
            "total": len(tasks),
            "counts": counts,
            "failed": sum(1 for t in tasks if t["execution_state"] in {"failed", "unsupported"}),
            "items": tasks,
        },
        "repositories": {
            "total": len(repos),
            "git": sum(1 for repo in repos if repo["is_git"]),
            "dirty": sum(1 for repo in repos if repo["dirty"]),
            "not_git": sum(1 for repo in repos if not repo["is_git"]),
            "items": repos,
        },
        "decisions": decisions,
    }


@app.route("/api/reports/operations")
def api_reports_operations():
    return jsonify(build_operations_report())


@app.route("/api/tools/status")
def api_tools_status():
    return jsonify(get_tools_status_cached())


@app.route("/api/acp/status")
def api_acp_status():
    company_dir, source = resolve_company_dir()
    scripts = get_acp_scripts()
    body: dict[str, Any] = {
        "company_dir": str(company_dir),
        "source": source,
        "scripts": scripts,
        "ok": False,
        "stdout": "",
        "stderr": "",
        "tools": {tool: {"target": target, "configured": False} for tool, target in ACP_TOOL_TARGET.items()},
    }
    status_script = scripts["status"]
    if not status_script["exists"] or not status_script["executable"]:
        body["stderr"] = "未找到可执行的 acp-all-status。"
        return jsonify(body)
    try:
        result = subprocess.run(
            [status_script["path"]],
            cwd=str(company_dir),
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=25,
        )
    except Exception as exc:
        body["stderr"] = str(exc)
        return jsonify(body)
    stdout = result.stdout or ""
    stderr = result.stderr or ""
    body["ok"] = result.returncode == 0
    body["stdout"] = stdout[-12000:]
    body["stderr"] = stderr[-4000:]
    for tool in body["tools"]:
        body["tools"][tool]["configured"] = tool in stdout and "[OK]" in stdout
    return jsonify(body)


@app.route("/api/acp/summary")
def api_acp_summary():
    company_dir, source = resolve_company_dir()
    scripts = get_acp_scripts()
    enabled = bool(scripts["agent"]["exists"] and scripts["agent"]["executable"])
    return jsonify(
        {
            "company_dir": str(company_dir),
            "source": source,
            "ok": enabled,
            "scripts": scripts,
            "tools": {tool: {"target": target, "configured": enabled} for tool, target in ACP_TOOL_TARGET.items()},
        }
    )


@app.route("/api/acp/token-routing")
def api_acp_token_routing():
    project = request.args.get("project", "")
    task_type = request.args.get("task_type", "fullstack")
    title = request.args.get("title", "")
    notes = request.args.get("notes", "")
    locked_scope = request.args.get("locked_scope", "")
    acceptance = request.args.get("acceptance_criteria", "")
    plans = {
        key: token_optimized_pipeline(key, project=project)
        for key in sorted(ALLOWED_TASK_TYPE)
    }
    current = token_optimized_pipeline(task_type, title, notes, locked_scope, acceptance, project)
    return jsonify(
        {
            "current": current,
            "plans": plans,
            "tool_profiles": TOOL_TOKEN_PROFILE,
        }
    )


@app.route("/api/tasks", methods=["GET"])
def api_tasks():
    init_db()
    filters = {
        "q": request.args.get("q", ""),
        "project": request.args.get("project", ""),
        "status": request.args.get("status", ""),
        "priority": request.args.get("priority", ""),
        "execution_state": request.args.get("execution_state", ""),
        "order_by": request.args.get("order_by", "updated_at"),
    }
    with closing(db_conn()) as conn:
        reconcile_task_statuses(conn)
        conn.commit()
        rows = fetch_tasks(conn, filters)
        tasks = [row_to_task(r) for r in rows]
    return jsonify(tasks)


@app.route("/api/tasks/export", methods=["GET"])
def api_tasks_export():
    init_db()
    filters = {
        "q": request.args.get("q", ""),
        "project": request.args.get("project", ""),
        "status": request.args.get("status", ""),
        "priority": request.args.get("priority", ""),
        "execution_state": request.args.get("execution_state", ""),
        "order_by": request.args.get("order_by", "updated_at"),
    }
    with closing(db_conn()) as conn:
        reconcile_task_statuses(conn)
        conn.commit()
        rows = fetch_tasks(conn, filters)

    headers = [
        "id",
        "title",
        "project",
        "assignee_ai",
        "status",
        "priority",
        "due_at",
        "execution_state",
        "execution_tool",
        "created_at",
        "updated_at",
    ]
    chunks: list[str] = []
    chunks.append(",".join(headers) + "\n")
    for row in rows:
        task = row_to_task(row)
        line = []
        for h in headers:
            value = str(task.get(h, "") or "")
            if any(ch in value for ch in [",", "\"", "\n"]):
                value = "\"" + value.replace("\"", "\"\"") + "\""
            line.append(value)
        chunks.append(",".join(line) + "\n")
    content = "".join(chunks)
    return Response(
        content,
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="tasks.csv"'},
    )


@app.route("/api/tasks/<int:task_id>/execution-report", methods=["GET"])
def api_task_execution_report(task_id: int):
    init_db()
    with closing(db_conn()) as conn:
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if row is None:
        return jsonify({"error": "task not found"}), 404
    report = build_task_execution_report(row_to_task(row))
    if request.args.get("format") == "markdown":
        return Response(report["markdown"], mimetype="text/markdown; charset=utf-8")
    return jsonify(report)


@app.route("/api/tasks", methods=["POST"])
def api_create_task():
    init_db()
    data = request.get_json(force=True, silent=False) or {}
    title = str(data.get("title", "")).strip()
    project = str(data.get("project", "")).strip()
    assignee_ai = str(data.get("assignee_ai", "Other")).strip()
    status = str(data.get("status", "待分配")).strip()
    priority = str(data.get("priority", "P1")).strip()
    task_type = normalize_task_type(data.get("task_type"))
    due_at = parse_due_at(data.get("due_at"))
    estimated_finish_at = parse_due_at(data.get("estimated_finish_at"))
    acceptance_criteria = str(data.get("acceptance_criteria", "")).strip()
    notes = str(data.get("notes", "")).strip()
    ai_instruction = str(data.get("ai_instruction", "")).strip()
    locked_scope = str(data.get("locked_scope", "")).strip()
    expected_output = str(data.get("expected_output", "")).strip()
    verification_command = str(data.get("verification_command", "")).strip()

    if not title:
        return jsonify({"error": "title is required"}), 400
    if not project:
        return jsonify({"error": "project is required"}), 400
    if status not in ALLOWED_STATUS:
        return jsonify({"error": f"invalid status: {status}"}), 400
    if priority not in ALLOWED_PRIORITY:
        return jsonify({"error": f"invalid priority: {priority}"}), 400
    if assignee_ai not in ALLOWED_AI:
        assignee_ai = "Other"
    routing_reason = ""
    if bool(data.get("auto_route")) or assignee_ai == "Other":
        route_plan = token_optimized_pipeline(task_type, title, f"{notes} {ai_instruction}", locked_scope, acceptance_criteria, project)
        assignee_ai = route_plan["primary_tool"]
        pipeline_text = " → ".join(step["tool"] for step in route_plan["pipeline"])
        routing_reason = f"{route_plan['reason']} Token 优先链路：{pipeline_text}。"

    ts = now_str()
    with closing(db_conn()) as conn:
        cur = conn.execute(
            """
            INSERT INTO tasks
            (title, project, assignee_ai, status, priority, due_at, acceptance_criteria, notes,
             estimated_finish_at, task_type, ai_instruction, locked_scope, expected_output,
             verification_command, routing_reason, execution_state, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'idle', ?, ?)
            """,
            (
                title,
                project,
                assignee_ai,
                status,
                priority,
                due_at,
                acceptance_criteria,
                notes,
                estimated_finish_at,
                task_type,
                ai_instruction,
                locked_scope,
                expected_output,
                verification_command,
                routing_reason,
                ts,
                ts,
            ),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (cur.lastrowid,)).fetchone()
    return jsonify(row_to_task(row)), 201


@app.route("/api/tasks/<int:task_id>", methods=["GET", "PATCH"])
def api_update_task(task_id: int):
    init_db()
    if request.method == "GET":
        with closing(db_conn()) as conn:
            reconcile_task_statuses(conn)
            conn.commit()
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None:
            return jsonify({"error": "task not found"}), 404
        return jsonify(row_to_task(row))

    data = request.get_json(force=True, silent=False) or {}
    fields: dict[str, Any] = {}
    if "title" in data:
        title = str(data["title"]).strip()
        if not title:
            return jsonify({"error": "title cannot be empty"}), 400
        fields["title"] = title
    if "project" in data:
        project = str(data["project"]).strip()
        if not project:
            return jsonify({"error": "project cannot be empty"}), 400
        fields["project"] = project
    if "assignee_ai" in data:
        ai = str(data["assignee_ai"]).strip()
        fields["assignee_ai"] = ai if ai in ALLOWED_AI else "Other"
    if "status" in data:
        st = str(data["status"]).strip()
        if st not in ALLOWED_STATUS:
            return jsonify({"error": f"invalid status: {st}"}), 400
        fields["status"] = st
    if "priority" in data:
        pr = str(data["priority"]).strip()
        if pr not in ALLOWED_PRIORITY:
            return jsonify({"error": f"invalid priority: {pr}"}), 400
        fields["priority"] = pr
    if "due_at" in data:
        fields["due_at"] = parse_due_at(data["due_at"])
    if "estimated_finish_at" in data:
        fields["estimated_finish_at"] = parse_due_at(data["estimated_finish_at"])
    if "acceptance_criteria" in data:
        fields["acceptance_criteria"] = str(data["acceptance_criteria"]).strip()
    if "notes" in data:
        fields["notes"] = str(data["notes"]).strip()
    if "task_type" in data:
        fields["task_type"] = normalize_task_type(data["task_type"])
    for text_field in ["ai_instruction", "locked_scope", "expected_output", "verification_command", "routing_reason", "delivery_evidence"]:
        if text_field in data:
            fields[text_field] = str(data[text_field]).strip() or None
    if not fields:
        return jsonify({"error": "no valid fields provided"}), 400
    fields["updated_at"] = now_str()
    set_clause = ", ".join([f"{k} = ?" for k in fields.keys()])
    values = list(fields.values()) + [task_id]
    with closing(db_conn()) as conn:
        cur = conn.execute(f"UPDATE tasks SET {set_clause} WHERE id = ?", values)
        conn.commit()
        if cur.rowcount == 0:
            return jsonify({"error": "task not found"}), 404
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    return jsonify(row_to_task(row))


@app.route("/api/tasks/<int:task_id>", methods=["DELETE"])
def api_delete_task(task_id: int):
    with closing(db_conn()) as conn:
        cur = conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        conn.commit()
        if cur.rowcount == 0:
            return jsonify({"error": "task not found"}), 404
    return jsonify({"ok": True})


@app.route("/api/tasks/bulk", methods=["POST"])
def api_bulk_update_tasks():
    init_db()
    data = request.get_json(force=True, silent=False) or {}
    ids = data.get("ids")
    status = str(data.get("status", "")).strip()
    if not isinstance(ids, list) or not ids:
        return jsonify({"error": "ids must be a non-empty array"}), 400
    task_ids: list[int] = []
    for item in ids:
        try:
            task_ids.append(int(item))
        except (TypeError, ValueError):
            return jsonify({"error": "ids must contain integers"}), 400

    if status not in ALLOWED_STATUS:
        return jsonify({"error": f"invalid status: {status}"}), 400

    placeholders = ",".join("?" for _ in task_ids)
    with closing(db_conn()) as conn:
        cur = conn.execute(
            f"UPDATE tasks SET status = ?, updated_at = ? WHERE id IN ({placeholders})",
            [status, now_str(), *task_ids],
        )
        conn.commit()
    return jsonify({"ok": True, "updated_count": cur.rowcount, "status": status})


@app.route("/api/tasks/<int:task_id>/review", methods=["POST"])
def api_review_task(task_id: int):
    init_db()
    data = request.get_json(force=True, silent=False) or {}
    decision = str(data.get("decision", "")).strip().lower()
    comment = str(data.get("comment", "")).strip()
    if decision not in {"approve", "reject"}:
        return jsonify({"error": "decision must be approve or reject"}), 400

    with closing(db_conn()) as conn:
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None:
            return jsonify({"error": "task not found"}), 404

        if decision == "approve":
            new_status = "已完成"
            review_result = "approved"
            progress_msg = "人工审查通过，任务闭环完成"
        else:
            new_status = "待分配"
            review_result = "rejected"
            progress_msg = f"人工审查驳回，任务重开。原因：{comment or '未填写'}"

        conn.execute(
            """
            UPDATE tasks
            SET status = ?, review_result = ?, review_comment = ?, reviewed_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (new_status, review_result, comment or None, now_str(), now_str(), task_id),
        )
        conn.commit()

    append_task_progress(task_id, progress_msg)
    with closing(db_conn()) as conn:
        updated = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    return jsonify(row_to_task(updated))


@app.route("/api/tool-routing-rules")
def api_tool_routing_rules():
    return jsonify({key: {"tool": value[0], "reason": value[1]} for key, value in TASK_TYPE_TOOL_ROUTE.items()})


@app.route("/api/tasks/<int:task_id>/route", methods=["POST"])
def api_route_task(task_id: int):
    init_db()
    with closing(db_conn()) as conn:
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None:
            return jsonify({"error": "task not found"}), 404
        plan = token_optimized_pipeline(
            row["task_type"],
            row["title"],
            f"{row['notes'] or ''} {row['ai_instruction'] or ''}",
            row["locked_scope"] or "",
            row["acceptance_criteria"] or "",
            row["project"] or "",
        )
        tool = plan["primary_tool"]
        pipeline_text = " → ".join(step["tool"] for step in plan["pipeline"])
        reason = f"{plan['reason']} Token 优先链路：{pipeline_text}。"
        conn.execute(
            "UPDATE tasks SET assignee_ai = ?, routing_reason = ?, updated_at = ? WHERE id = ?",
            (tool, reason, now_str(), task_id),
        )
        conn.commit()
        updated = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    append_task_progress(task_id, f"智能路由：{tool}。{reason}")
    return jsonify({"ok": True, "tool": tool, "reason": reason, "task": row_to_task(updated)})


@app.route("/api/tasks/<int:task_id>/dispatch", methods=["POST"])
def api_dispatch_task(task_id: int):
    init_db()
    with closing(db_conn()) as conn:
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None:
            return jsonify({"error": "task not found"}), 404
        if row["execution_state"] == "running":
            return jsonify({"error": "task is already running"}), 400
    t = threading.Thread(target=dispatch_task_worker, args=(task_id,), daemon=True)
    t.start()
    return jsonify({"ok": True, "task_id": task_id, "message": "dispatch started"})


@app.route("/api/tasks/<int:task_id>/retry", methods=["POST"])
def api_retry_task(task_id: int):
    init_db()
    with closing(db_conn()) as conn:
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None:
            return jsonify({"error": "task not found"}), 404
        if row["execution_state"] == "running":
            return jsonify({"error": "task is already running"}), 400
        route_plan = token_optimized_pipeline(
            row["task_type"],
            row["title"],
            f"{row['notes'] or ''} {row['ai_instruction'] or ''}",
            row["locked_scope"] or "",
            row["acceptance_criteria"] or "",
            row["project"] or "",
        )
        routed_tool = route_plan["primary_tool"]
        pipeline_text = " → ".join(step["tool"] for step in route_plan["pipeline"])
        routing_reason = f"{route_plan['reason']} Token 优先链路：{pipeline_text}。"
        conn.execute(
            """
            UPDATE tasks
            SET status = '待分配',
                assignee_ai = ?,
                routing_reason = ?,
                execution_state = 'idle',
                execution_tool = NULL,
                execution_command = NULL,
                execution_output = NULL,
                execution_error = NULL,
                execution_progress = NULL,
                execution_started_at = NULL,
                execution_finished_at = NULL,
                review_result = NULL,
                review_comment = NULL,
                reviewed_at = NULL,
                updated_at = ?
            WHERE id = ?
            """,
            (routed_tool, routing_reason, now_str(), task_id),
        )
        conn.commit()

    append_task_progress(task_id, f"已重置任务执行状态，按 Token 优先策略重新路由到 {routed_tool}：{pipeline_text}")
    t = threading.Thread(target=dispatch_task_worker, args=(task_id,), daemon=True)
    t.start()
    return jsonify({"ok": True, "task_id": task_id, "message": "retry started"})


@app.route("/api/dashboard-summary")
def api_dashboard_summary():
    init_db()
    with closing(db_conn()) as conn:
        reconcile_task_statuses(conn)
        conn.commit()
        counts = get_task_counts(conn)
        overdue = get_overdue_tasks(conn)
        due_soon = get_due_soon_tasks(conn)
        running = conn.execute("SELECT COUNT(*) FROM tasks WHERE execution_state = 'running'").fetchone()[0]
        failed = conn.execute("SELECT COUNT(*) FROM tasks WHERE execution_state = 'failed'").fetchone()[0]
    return jsonify(
        {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "active_projects": len(list_projects()),
            "counts": counts,
            "overdue_count": len(overdue),
            "due_soon_count": len(due_soon),
            "running_dispatch_count": running,
            "failed_dispatch_count": failed,
        }
    )


@app.route("/api/daily-brief")
def api_daily_brief():
    init_db()
    with closing(db_conn()) as conn:
        reconcile_task_statuses(conn)
        conn.commit()
        overdue = [row_to_task(r) for r in get_overdue_tasks(conn)]
        due_soon = [row_to_task(r) for r in get_due_soon_tasks(conn)]
        counts = get_task_counts(conn)
        failed = conn.execute(
            "SELECT id, title, project, execution_error FROM tasks WHERE execution_state = 'failed' ORDER BY updated_at DESC LIMIT 5"
        ).fetchall()
    warnings = []
    if counts.get("待人工审查", 0) > 3:
        warnings.append("待人工审查任务超过 3 个，建议先清理审查队列。")
    if overdue:
        warnings.append(f"存在 {len(overdue)} 个超时任务，请优先处理。")
    if len(list_projects()) > 5:
        warnings.append("活跃项目超过 5 个，建议评估归档。")
    if failed:
        warnings.append(f"存在 {len(failed)} 个自动调度失败任务，请查看执行日志。")
    return jsonify(
        {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "warnings": warnings,
            "overdue_tasks": overdue,
            "due_soon_tasks": due_soon,
            "failed_dispatch_tasks": [
                {"id": r["id"], "title": r["title"], "project": r["project"], "error": r["execution_error"]} for r in failed
            ],
        }
    )


@app.route("/api/decision-logs", methods=["GET", "POST"])
def api_decision_logs():
    init_db()
    if request.method == "GET":
        project = (request.args.get("project") or "").strip()
        try:
            limit = max(1, min(100, int(request.args.get("limit", "30"))))
        except ValueError:
            limit = 30
        filters = []
        values: list[Any] = []
        if project:
            filters.append("project = ?")
            values.append(project)
        where = f"WHERE {' AND '.join(filters)}" if filters else ""
        with closing(db_conn()) as conn:
            rows = conn.execute(f"SELECT * FROM decision_logs {where} ORDER BY created_at DESC LIMIT ?", [*values, limit]).fetchall()
        return jsonify([row_to_decision(r) for r in rows])

    data = request.get_json(force=True, silent=False) or {}
    project = str(data.get("project", "")).strip()
    decision = str(data.get("decision", "")).strip()
    name_error = validate_project_name(project)
    if name_error:
        return jsonify({"error": name_error}), 400
    if not decision:
        return jsonify({"error": "decision is required"}), 400
    with closing(db_conn()) as conn:
        cur = conn.execute(
            """
            INSERT INTO decision_logs (project, decision, context, reason, impact, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                project,
                decision,
                str(data.get("context", "")).strip(),
                str(data.get("reason", "")).strip(),
                str(data.get("impact", "")).strip(),
                now_str(),
            ),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM decision_logs WHERE id = ?", (cur.lastrowid,)).fetchone()
    return jsonify(row_to_decision(row)), 201


@app.route("/api/operations/command-center")
def api_operations_command_center():
    init_db()
    with closing(db_conn()) as conn:
        counts = get_task_counts(conn)
        overdue = [row_to_task(r) for r in get_overdue_tasks(conn)]
        due_soon = [row_to_task(r) for r in get_due_soon_tasks(conn, minutes=240)]
        review = [row_to_task(r) for r in conn.execute("SELECT * FROM tasks WHERE status = '待人工审查' ORDER BY updated_at ASC LIMIT 8").fetchall()]
        failed = [
            row_to_task(r)
            for r in conn.execute(
                "SELECT * FROM tasks WHERE execution_state IN ('failed', 'unsupported') ORDER BY updated_at DESC LIMIT 8"
            ).fetchall()
        ]
        unrouted = [
            row_to_task(r)
            for r in conn.execute(
                "SELECT * FROM tasks WHERE (routing_reason IS NULL OR routing_reason = '') AND status != '已完成' ORDER BY priority ASC, created_at ASC LIMIT 8"
            ).fetchall()
        ]
        recent_decisions = [
            row_to_decision(r)
            for r in conn.execute("SELECT * FROM decision_logs ORDER BY created_at DESC LIMIT 5").fetchall()
        ]

    next_actions = []
    if review:
        next_actions.append({"level": "P0", "title": f"先处理 {len(review)} 个待人工审查任务", "action": "review_queue"})
    if failed:
        next_actions.append({"level": "P0", "title": f"修复 {len(failed)} 个调度失败任务", "action": "fix_failed_dispatch"})
    if overdue:
        next_actions.append({"level": "P0", "title": f"推进 {len(overdue)} 个超时任务", "action": "resolve_overdue"})
    if unrouted:
        next_actions.append({"level": "P1", "title": f"为 {len(unrouted)} 个任务执行智能路由", "action": "route_tasks"})
    if not next_actions:
        next_actions.append({"level": "P2", "title": "当前队列健康，建议创建下一批高价值任务", "action": "plan_next"})

    return jsonify(
        {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "counts": counts,
            "next_actions": next_actions,
            "review_queue": review,
            "failed_dispatch_tasks": failed,
            "overdue_tasks": overdue,
            "due_soon_tasks": due_soon,
            "unrouted_tasks": unrouted,
            "recent_decisions": recent_decisions,
        }
    )


@app.route("/api/health")
def api_health():
    company_dir, source = resolve_company_dir()
    desktop_access = is_dir_accessible(DESKTOP_COMPANY_DIR)
    safe_access = is_dir_accessible(SAFE_COMPANY_DIR)
    legacy_access = is_dir_accessible(LEGACY_COMPANY_DIR)
    pm_exists = PM_SCRIPT.exists()

    tools = {}
    for tool in ["Cursor", "Antigravity", "Claude Code", "Codex", "Gemini"]:
        cmd = resolve_tool_command(tool)
        tools[tool] = {"available": cmd is not None, "command": cmd}

    return jsonify(
        {
            "now": now_str(),
            "company_dir_in_use": str(company_dir),
            "company_source": source,
            "paths": {
                "safe_company": {"path": str(SAFE_COMPANY_DIR), "accessible": safe_access},
                "desktop_company": {"path": str(DESKTOP_COMPANY_DIR), "accessible": desktop_access},
                "legacy_company": {"path": str(LEGACY_COMPANY_DIR), "accessible": legacy_access},
            },
            "pm_script": {"path": str(PM_SCRIPT), "exists": pm_exists},
            "acp": get_acp_scripts(),
            "launchd": launchd_service_status(),
            "runtime_config": {
                "host": get_configured_host(),
                "port": get_configured_port(),
                "dispatch_timeout_seconds": get_dispatch_timeout_seconds(),
            },
            "settings": load_settings(),
            "tools": tools,
        }
    )


@app.route("/api/settings", methods=["GET", "PATCH"])
def api_settings():
    if request.method == "GET":
        return jsonify(
            {
                "settings": load_settings(),
                "routing_rules": {key: {"tool": value[0], "reason": value[1]} for key, value in TASK_TYPE_TOOL_ROUTE.items()},
                "allowed": {
                    "task_types": sorted(ALLOWED_TASK_TYPE),
                    "assignee_ai": sorted(ALLOWED_AI),
                },
            }
        )

    data = request.get_json(force=True, silent=False) or {}
    allowed_keys = {
        "dispatch_timeout_seconds",
        "auto_route_new_tasks",
        "dashboard_refresh_seconds",
        "default_task_type",
        "default_assignee_ai",
    }
    incoming = {k: data[k] for k in allowed_keys if k in data}
    settings = save_settings(incoming)
    return jsonify({"ok": True, "settings": settings})


@app.route("/api/settings/reset", methods=["POST"])
def api_settings_reset():
    try:
        SETTINGS_PATH.unlink()
    except FileNotFoundError:
        pass
    return jsonify({"ok": True, "settings": load_settings()})


@app.route("/api/settings/refresh-tools", methods=["POST"])
def api_settings_refresh_tools():
    _TOOL_STATUS_CACHE["ts"] = None
    _TOOL_STATUS_CACHE["data"] = None
    return jsonify({"ok": True, "tools": get_tools_status_cached()})
