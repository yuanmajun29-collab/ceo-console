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

from flask import jsonify, render_template, request, send_from_directory
from flask import Response

from .core import app
from .config import APP_DIR
from . import finance as _finance_mod
from .finance import (
    OCR_SUPPORTED_MIME_TYPES,
    compute_overview as finance_compute_overview,
    delete_subscription as finance_delete_subscription,
    delete_transaction as finance_delete_transaction,
    import_transactions_from_csv as finance_import_csv,
    insert_subscription as finance_insert_subscription,
    insert_transaction as finance_insert_transaction,
    is_ocr_configured as finance_is_ocr_configured,
    list_subscriptions as finance_list_subscriptions,
    list_transactions as finance_list_transactions,
    ocr_receipt as finance_ocr_receipt,
    patch_subscription as finance_patch_subscription,
)
from .config import *
from .db import db_conn, init_db
from .dispatch import append_task_progress, dispatch_task_worker, launchd_service_status
from .projects import *
from .tasks import *
from .tools import *
from .tools import _TOOL_STATUS_CACHE
from .config import _ACP_DISCOVERY_CACHE

_ACP_DISCOVERY_REFRESH_LOCK = threading.Lock()


def invalidate_tools_status_cache() -> None:
    _TOOL_STATUS_CACHE["ts"] = None
    _TOOL_STATUS_CACHE["data"] = None


def refresh_acp_discovery_from_status(force: bool = False, timeout: int = 8) -> dict[str, Any]:
    scripts = get_acp_scripts()
    company_dir, _ = resolve_company_dir()
    status_script = scripts["status"]
    result: dict[str, Any] = {
        "ok": False,
        "stdout": "",
        "stderr": "",
        "skipped": False,
        "refreshed": False,
        "removed_tools": [],
        "added_tools": [],
    }

    if not status_script["exists"] or not status_script["executable"]:
        before = set(get_acp_agent_registry().keys())
        clear_acp_discovery_cache()
        after = set(get_acp_agent_registry().keys())
        if before != after:
            invalidate_tools_status_cache()
        result["stderr"] = "未找到可执行的 acp-all-status。"
        result["removed_tools"] = sorted(before - after)
        return result

    with _ACP_DISCOVERY_REFRESH_LOCK:
        age = acp_discovery_cache_age_seconds()
        if not force and age is not None and age < max(0, ACP_DISCOVERY_REFRESH_SECONDS):
            result["ok"] = True
            result["skipped"] = True
            result["stdout"] = _ACP_DISCOVERY_CACHE.get("stdout") or ""
            return result

        before = set(get_acp_agent_registry().keys())
        try:
            proc = subprocess.run(
                [status_script["path"]],
                cwd=str(company_dir),
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=timeout,
            )
        except Exception as exc:
            result["stderr"] = str(exc)
            return result

        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
        result["ok"] = proc.returncode == 0
        result["stdout"] = stdout
        result["stderr"] = stderr
        result["refreshed"] = True
        get_acp_agent_registry(stdout)
        after = set(get_acp_agent_registry().keys())
        result["removed_tools"] = sorted(before - after)
        result["added_tools"] = sorted(after - before)
        if before != after:
            invalidate_tools_status_cache()
        return result


SPA_DIST_DIR = APP_DIR / "static" / "app"


@app.route("/")
def root_redirect():
    # New SPA is mounted at /app/. If it has been built, redirect there; otherwise
    # fall back to the legacy single-page dashboard so existing tests keep passing.
    if (SPA_DIST_DIR / "index.html").exists():
        return Response(status=302, headers={"Location": "/app/"})
    return render_template("dashboard.html")


@app.route("/legacy")
def legacy_dashboard() -> str:
    return render_template("dashboard.html")


@app.route("/app/")
@app.route("/app")
def spa_index():
    index_file = SPA_DIST_DIR / "index.html"
    if not index_file.exists():
        return Response(
            "<h1>CEO Console SPA 未构建</h1>"
            "<p>请在 <code>frontend/</code> 目录运行 <code>npm install && npm run build</code>，"
            "然后刷新本页。开发模式可运行 <code>npm run dev</code> 并直接访问 "
            "<a href=\"http://127.0.0.1:5173/app/\">http://127.0.0.1:5173/app/</a>。</p>",
            status=503,
            mimetype="text/html; charset=utf-8",
        )
    return send_from_directory(SPA_DIST_DIR, "index.html")


@app.route("/app/<path:resource>")
def spa_asset(resource: str):
    asset_path = SPA_DIST_DIR / resource
    if asset_path.exists() and asset_path.is_file():
        return send_from_directory(SPA_DIST_DIR, resource)
    # client-side routing: any unknown sub-path returns index.html
    index_file = SPA_DIST_DIR / "index.html"
    if index_file.exists():
        return send_from_directory(SPA_DIST_DIR, "index.html")
    return Response("SPA not built", status=503)


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
    business_os = build_company_operating_system()
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
        "business_os": business_os,
    }


@app.route("/api/reports/operations")
def api_reports_operations():
    return jsonify(build_operations_report())


def business_task_status(task: dict[str, Any]) -> str:
    if task.get("execution_state") == "succeeded" and task.get("review_result") == "approved":
        return "已完成"
    if task.get("execution_state") == "succeeded" and task.get("status") == "AI执行中":
        return "待人工审查"
    if task.get("execution_state") in {"failed", "unsupported"} and task.get("status") == "AI执行中":
        return "待分配"
    return task.get("status") or "待分配"


def business_task_ref(task: dict[str, Any]) -> dict[str, Any]:
    error = task.get("execution_error") or ""
    return {
        "id": task.get("id"),
        "title": task.get("title"),
        "project": task.get("project"),
        "task_type": task.get("task_type"),
        "status": business_task_status(task),
        "raw_status": task.get("status"),
        "execution_state": task.get("execution_state"),
        "assignee_ai": task.get("assignee_ai"),
        "priority": task.get("priority"),
        "due_at": task.get("due_at"),
        "updated_at": task.get("updated_at"),
        "execution_error": error[:240] if error else None,
    }


def build_business_decision_queue(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    queue: list[dict[str, Any]] = []
    for task in tasks:
        status = business_task_status(task)
        state = task.get("execution_state")
        due_at = parse_datetime_value(task.get("due_at"))
        overdue = bool(due_at and due_at < datetime.now() and status not in {"已完成"})
        if status == "待人工审查":
            queue.append({"level": "P0", "task": business_task_ref(task), "reason": "等待 CEO 验收", "action": "approve_or_reject"})
        elif state in {"failed", "unsupported"}:
            reason = (task.get("execution_error") or "自动调度失败")[:240]
            queue.append({"level": "P0", "task": business_task_ref(task), "reason": reason, "action": "retry_or_rewrite"})
        elif overdue:
            queue.append({"level": "P1", "task": business_task_ref(task), "reason": "任务已超期", "action": "reprioritize"})
    priority_rank = {"P0": 0, "P1": 1, "P2": 2}
    queue.sort(key=lambda item: (priority_rank.get(item["level"], 9), item["task"].get("updated_at") or ""), reverse=False)
    return queue[:8]


def build_company_operating_system() -> dict[str, Any]:
    init_db()
    with closing(db_conn()) as conn:
        reconcile_task_statuses(conn)
        conn.commit()
        tasks = [row_to_task(r) for r in fetch_tasks(conn)]
        counts = get_task_counts(conn)

    modules = []
    for key, spec in BUSINESS_MODULES.items():
        module_types = set(spec["task_types"])
        module_tasks = [task for task in tasks if task.get("task_type") in module_types]
        active = [task for task in module_tasks if business_task_status(task) not in {"已完成"}]
        review = [task for task in module_tasks if business_task_status(task) == "待人工审查"]
        failed = [task for task in module_tasks if task.get("execution_state") in {"failed", "unsupported"}]
        latest = sorted(module_tasks, key=lambda task: task.get("updated_at") or "", reverse=True)[:1]
        route_plan = token_optimized_pipeline(spec["default_task_type"], apply_availability=True)
        route_steps = route_plan.get("execution_pipeline") or route_plan.get("pipeline") or []
        modules.append(
            {
                "key": key,
                "name": spec["name"],
                "domain": spec.get("domain"),
                "tagline": spec["tagline"],
                "task_types": spec["task_types"],
                "toolchain": spec["toolchain"],
                "ceo_actions": spec["ceo_actions"],
                "default_task_type": spec["default_task_type"],
                "task_template": spec["task_template"],
                "stats": {
                    "total": len(module_tasks),
                    "active": len(active),
                    "review": len(review),
                    "failed": len(failed),
                },
                "route": {
                    "primary_tool": route_plan.get("primary_tool"),
                    "recommended_tool": route_plan.get("recommended_tool"),
                    "reason": route_plan.get("reason"),
                    "execution_chain": [step.get("tool") for step in route_steps],
                    "fallback_applied": route_plan.get("fallback_applied"),
                    "skipped_tools": route_plan.get("skipped_tools") or [],
                },
                "latest_task": business_task_ref(latest[0]) if latest else None,
            }
        )

    decision_queue = build_business_decision_queue(tasks)
    domain_summaries: list[dict[str, Any]] = []
    module_index = {m["key"]: m for m in modules}
    for d_key, d_spec in BUSINESS_DOMAINS.items():
        d_modules = [module_index[m_key] for m_key in d_spec["modules"] if m_key in module_index]
        d_stats_total = sum(m["stats"]["total"] for m in d_modules)
        d_stats_review = sum(m["stats"]["review"] for m in d_modules)
        d_stats_failed = sum(m["stats"]["failed"] for m in d_modules)
        d_stats_active = sum(m["stats"]["active"] for m in d_modules)
        domain_summaries.append(
            {
                "key": d_key,
                "name": d_spec["name"],
                "tagline": d_spec["tagline"],
                "module_keys": d_spec["modules"],
                "stats": {
                    "total": d_stats_total,
                    "active": d_stats_active,
                    "review": d_stats_review,
                    "failed": d_stats_failed,
                },
            }
        )

    return {
        "generated_at": now_str(),
        "principle": "CEO 只做三件事：看经营态势、说目标指令、点批准或驳回。",
        "layers": [
            {"name": "Web CEO 驾驶舱", "role": "统一呈现日报、任务、风险和待决策队列"},
            {"name": "任务路由器", "role": "把自然语言目标拆成任务类型、上下文范围和低 Token 链路"},
            {"name": "Agent 编排器", "role": "通过 ACP 调度 Cursor / Antigravity / OpenClaw / Hermes / Claude / Codex / Gemini / DeepSeek"},
            {"name": "上下文总线", "role": "注入项目文档、决策日志、客户/财务/营销资料摘要"},
            {"name": "人机协作网关", "role": "低风险自动推进，高风险交给 CEO 审批"},
        ],
        "interaction_modes": [
            {"name": "看", "description": "查看 AI 巡航摘要、风险、待评审与报表"},
            {"name": "说", "description": "用自然语言创建经营任务或补充审批意见"},
            {"name": "点", "description": "批准、驳回、重试、发布、合并或确认入账"},
        ],
        "counts": counts,
        "domains": domain_summaries,
        "modules": modules,
        "decision_queue": decision_queue,
    }


@app.route("/api/company-operating-system")
def api_company_operating_system():
    return jsonify(build_company_operating_system())


@app.route("/api/tools/status")
def api_tools_status():
    refresh_acp_discovery_from_status(timeout=10)
    return jsonify(get_tools_status_cached())


@app.route("/api/acp/status")
def api_acp_status():
    company_dir, source = resolve_company_dir()
    scripts = get_acp_scripts()
    refresh = refresh_acp_discovery_from_status(force=True, timeout=25)
    body: dict[str, Any] = {
        "company_dir": str(company_dir),
        "source": source,
        "scripts": scripts,
        "ok": refresh["ok"],
        "stdout": (refresh["stdout"] or "")[-12000:],
        "stderr": (refresh["stderr"] or "")[-4000:],
        "refreshed": refresh["refreshed"],
        "skipped": refresh["skipped"],
        "removed_tools": refresh["removed_tools"],
        "added_tools": refresh["added_tools"],
        "tools": get_acp_agent_registry(),
    }
    return jsonify(body)


@app.route("/api/acp/summary")
def api_acp_summary():
    company_dir, source = resolve_company_dir()
    refresh = refresh_acp_discovery_from_status(timeout=10)
    scripts = get_acp_scripts()
    enabled = bool(scripts["agent"]["exists"] and scripts["agent"]["executable"])
    registry = get_acp_agent_registry()
    tools = {
        name: {**entry, "configured": bool(entry.get("configured") or (enabled and entry.get("builtin")))}
        for name, entry in registry.items()
    }
    return jsonify(
        {
            "company_dir": str(company_dir),
            "source": source,
            "ok": enabled,
            "discovery": {
                "refreshed": refresh["refreshed"],
                "skipped": refresh["skipped"],
                "removed_tools": refresh["removed_tools"],
                "added_tools": refresh["added_tools"],
                "last_checked_at": _ACP_DISCOVERY_CACHE.get("ts"),
                "stderr": (refresh["stderr"] or "")[-1000:],
            },
            "scripts": scripts,
            "tools": tools,
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
        key: token_optimized_pipeline(key, project=project, apply_availability=True)
        for key in sorted(ALLOWED_TASK_TYPE)
    }
    current = token_optimized_pipeline(task_type, title, notes, locked_scope, acceptance, project, apply_availability=True)
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


def _read_byte_range(path: Path, start: int, end: int) -> tuple[str, int]:
    """Read bytes [start, end) from path, return (decoded text, bytes_read)."""
    if end <= start:
        return "", 0
    with path.open("rb") as f:
        f.seek(start)
        data = f.read(end - start)
    return data.decode("utf-8", errors="replace"), len(data)


@app.route("/api/tasks/<int:task_id>/log-stream", methods=["GET"])
def api_task_log_stream(task_id: int):
    """Server-Sent Events stream of the latest run log for a task.

    Sends an `init` event with the current tail, then `append` events for new
    bytes as the file grows. Closes with a `done` event when the task leaves
    the running state, or after a long idle window with no file activity.
    """
    init_db()
    with closing(db_conn()) as conn:
        row = conn.execute(
            "SELECT id, execution_state FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
    if row is None:
        return jsonify({"error": "task not found"}), 404

    poll_interval = 1.0
    max_idle_ticks = 120  # 2 minutes of no activity before auto-close

    def stream():
        log_path = latest_task_log_path(task_id)
        if log_path and log_path.exists():
            initial = read_file_tail(log_path, max_chars=12000)
            cursor = log_path.stat().st_size
            yield (
                "event: init\ndata: "
                + json.dumps(
                    {"content": initial, "log_path": str(log_path)},
                    ensure_ascii=False,
                )
                + "\n\n"
            )
        else:
            cursor = 0
            yield "event: init\ndata: " + json.dumps({"content": "", "log_path": None}) + "\n\n"

        idle = 0
        while True:
            time.sleep(poll_interval)

            # Re-resolve the latest log path each tick. A retry can rotate to
            # a brand-new file, in which case we reset the cursor.
            latest = latest_task_log_path(task_id)
            if latest is None:
                idle += 1
                yield ": heartbeat\n\n"
            else:
                if log_path != latest:
                    log_path = latest
                    cursor = 0
                    yield "event: rotate\ndata: " + json.dumps(
                        {"log_path": str(log_path)}, ensure_ascii=False
                    ) + "\n\n"
                try:
                    size = log_path.stat().st_size
                except OSError:
                    size = cursor
                if size > cursor:
                    chunk, read = _read_byte_range(log_path, cursor, size)
                    cursor += read
                    if chunk:
                        idle = 0
                        yield "event: append\ndata: " + json.dumps(
                            {"content": chunk}, ensure_ascii=False
                        ) + "\n\n"
                    else:
                        idle += 1
                        yield ": heartbeat\n\n"
                else:
                    idle += 1
                    yield ": heartbeat\n\n"

            with closing(db_conn()) as state_conn:
                state_row = state_conn.execute(
                    "SELECT execution_state FROM tasks WHERE id = ?", (task_id,)
                ).fetchone()
            current_state = state_row["execution_state"] if state_row else None
            if current_state in {"succeeded", "failed", "unsupported"}:
                yield "event: done\ndata: " + json.dumps(
                    {"state": current_state}, ensure_ascii=False
                ) + "\n\n"
                return

            if idle >= max_idle_ticks:
                yield "event: timeout\ndata: " + json.dumps(
                    {"reason": "no activity"}, ensure_ascii=False
                ) + "\n\n"
                return

    return Response(
        stream(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
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
    if not is_allowed_ai_name(assignee_ai):
        assignee_ai = "Other"
    routing_reason = ""
    if bool(data.get("auto_route")) or assignee_ai == "Other":
        route_plan = token_optimized_pipeline(task_type, title, f"{notes} {ai_instruction}", locked_scope, acceptance_criteria, project, apply_availability=True)
        assignee_ai = route_plan["primary_tool"]
        routing_reason = format_route_plan_reason(route_plan)

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
        fields["assignee_ai"] = ai if is_allowed_ai_name(ai) else "Other"
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
            apply_availability=True,
        )
        tool = plan["primary_tool"]
        reason = format_route_plan_reason(plan)
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
            apply_availability=True,
        )
        routed_tool = route_plan["primary_tool"]
        pipeline_text = " → ".join(step["tool"] for step in (route_plan.get("execution_pipeline") or route_plan.get("pipeline") or []))
        routing_reason = format_route_plan_reason(route_plan)
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


BULK_DISPATCH_MAX = 50


def _parse_bulk_ids(data: dict[str, Any]) -> tuple[list[int] | None, tuple[Response, int] | None]:
    ids = data.get("ids")
    if not isinstance(ids, list) or not ids:
        return None, (jsonify({"error": "ids must be a non-empty array"}), 400)
    task_ids: list[int] = []
    seen: set[int] = set()
    for item in ids:
        try:
            tid = int(item)
        except (TypeError, ValueError):
            return None, (jsonify({"error": "ids must contain integers"}), 400)
        if tid in seen:
            continue
        seen.add(tid)
        task_ids.append(tid)
    if len(task_ids) > BULK_DISPATCH_MAX:
        return None, (
            jsonify({"error": f"too many ids (max {BULK_DISPATCH_MAX} per batch)"}),
            400,
        )
    return task_ids, None


@app.route("/api/tasks/bulk-dispatch", methods=["POST"])
def api_bulk_dispatch_tasks():
    init_db()
    data = request.get_json(force=True, silent=False) or {}
    task_ids, err = _parse_bulk_ids(data)
    if err is not None:
        return err

    queued: list[int] = []
    skipped: list[dict[str, Any]] = []
    with closing(db_conn()) as conn:
        for tid in task_ids or []:
            row = conn.execute(
                "SELECT id, execution_state, status FROM tasks WHERE id = ?", (tid,)
            ).fetchone()
            if row is None:
                skipped.append({"id": tid, "reason": "task not found"})
                continue
            if row["execution_state"] == "running":
                skipped.append({"id": tid, "reason": "task is already running"})
                continue
            queued.append(tid)

    for tid in queued:
        threading.Thread(target=dispatch_task_worker, args=(tid,), daemon=True).start()

    return jsonify(
        {
            "ok": True,
            "queued_count": len(queued),
            "queued_ids": queued,
            "skipped": skipped,
            "message": f"已发起 {len(queued)} 个任务调度",
        }
    )


@app.route("/api/tasks/bulk-retry", methods=["POST"])
def api_bulk_retry_tasks():
    init_db()
    data = request.get_json(force=True, silent=False) or {}
    task_ids, err = _parse_bulk_ids(data)
    if err is not None:
        return err

    queued: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    ts = now_str()
    with closing(db_conn()) as conn:
        for tid in task_ids or []:
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (tid,)).fetchone()
            if row is None:
                skipped.append({"id": tid, "reason": "task not found"})
                continue
            if row["execution_state"] == "running":
                skipped.append({"id": tid, "reason": "task is already running"})
                continue
            route_plan = token_optimized_pipeline(
                row["task_type"],
                row["title"],
                f"{row['notes'] or ''} {row['ai_instruction'] or ''}",
                row["locked_scope"] or "",
                row["acceptance_criteria"] or "",
                row["project"] or "",
                apply_availability=True,
            )
            routed_tool = route_plan["primary_tool"]
            routing_reason = format_route_plan_reason(route_plan)
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
                (routed_tool, routing_reason, ts, tid),
            )
            queued.append({"id": tid, "tool": routed_tool})
        conn.commit()

    for entry in queued:
        tid = entry["id"]
        append_task_progress(tid, f"批量重试：已重置并重新路由到 {entry['tool']}")
        threading.Thread(target=dispatch_task_worker, args=(tid,), daemon=True).start()

    return jsonify(
        {
            "ok": True,
            "queued_count": len(queued),
            "queued": queued,
            "skipped": skipped,
            "message": f"已重试 {len(queued)} 个失败任务",
        }
    )


@app.route("/api/tasks/bulk-review", methods=["POST"])
def api_bulk_review_tasks():
    init_db()
    data = request.get_json(force=True, silent=False) or {}
    task_ids, err = _parse_bulk_ids(data)
    if err is not None:
        return err
    decision = str(data.get("decision", "")).strip().lower()
    comment = str(data.get("comment", "")).strip() or None
    if decision not in {"approve", "reject"}:
        return jsonify({"error": "decision must be approve or reject"}), 400

    applied: list[int] = []
    skipped: list[dict[str, Any]] = []
    new_status = "已完成" if decision == "approve" else "待分配"
    review_result = "approved" if decision == "approve" else "rejected"
    progress_template = (
        "批量人工审查通过，任务闭环完成"
        if decision == "approve"
        else f"批量人工审查驳回，任务重开。原因：{comment or '未填写'}"
    )
    ts = now_str()
    with closing(db_conn()) as conn:
        for tid in task_ids or []:
            row = conn.execute(
                "SELECT id, status FROM tasks WHERE id = ?", (tid,)
            ).fetchone()
            if row is None:
                skipped.append({"id": tid, "reason": "task not found"})
                continue
            if row["status"] != "待人工审查":
                skipped.append(
                    {"id": tid, "reason": f"task is in '{row['status']}', not '待人工审查'"}
                )
                continue
            conn.execute(
                """
                UPDATE tasks
                SET status = ?, review_result = ?, review_comment = ?, reviewed_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (new_status, review_result, comment, ts, ts, tid),
            )
            applied.append(tid)
        conn.commit()

    for tid in applied:
        append_task_progress(tid, progress_template)

    return jsonify(
        {
            "ok": True,
            "applied_count": len(applied),
            "applied_ids": applied,
            "skipped": skipped,
            "decision": decision,
            "message": f"已{('通过' if decision == 'approve' else '驳回')} {len(applied)} 个任务",
        }
    )


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
    for tool in CORE_AI_TOOLS:
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
        refresh_acp_discovery_from_status(timeout=10)
        return jsonify(
            {
                "settings": load_settings(),
                "routing_rules": {key: {"tool": value[0], "reason": value[1]} for key, value in TASK_TYPE_TOOL_ROUTE.items()},
                "allowed": {
                    "task_types": sorted(ALLOWED_TASK_TYPE),
                    "assignee_ai": sorted(allowed_ai_names()),
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
    refresh_acp_discovery_from_status(force=True, timeout=15)
    invalidate_tools_status_cache()
    return jsonify({"ok": True, "tools": get_tools_status_cached()})


@app.route("/api/finance/overview", methods=["GET"])
def api_finance_overview():
    init_db()
    return jsonify(finance_compute_overview())


@app.route("/api/finance/transactions", methods=["GET", "POST"])
def api_finance_transactions():
    init_db()
    if request.method == "GET":
        filters = {
            "month": request.args.get("month", ""),
            "direction": request.args.get("direction", ""),
            "category": request.args.get("category", ""),
            "project": request.args.get("project", ""),
        }
        return jsonify(finance_list_transactions(filters))
    data = request.get_json(force=True, silent=False) or {}
    inserted, err = finance_insert_transaction(data)
    if err is not None:
        return jsonify({"error": err}), 400
    return jsonify(inserted), 201


@app.route("/api/finance/transactions/<int:tid>", methods=["DELETE"])
def api_finance_delete_transaction(tid: int):
    init_db()
    if not finance_delete_transaction(tid):
        return jsonify({"error": "transaction not found"}), 404
    return jsonify({"ok": True})


@app.route("/api/finance/transactions/import-csv", methods=["POST"])
def api_finance_import_csv():
    init_db()
    raw_csv = request.get_data(as_text=True) or ""
    if not raw_csv.strip():
        return jsonify({"error": "csv body is empty"}), 400
    result = finance_import_csv(raw_csv)
    status = 200 if result.get("imported", 0) > 0 or not result.get("error") else 400
    return jsonify(result), status


@app.route("/api/finance/subscriptions", methods=["GET", "POST"])
def api_finance_subscriptions():
    init_db()
    if request.method == "GET":
        status = request.args.get("status", "").strip().lower() or None
        return jsonify(finance_list_subscriptions(status))
    data = request.get_json(force=True, silent=False) or {}
    inserted, err = finance_insert_subscription(data)
    if err is not None:
        return jsonify({"error": err}), 400
    return jsonify(inserted), 201


@app.route("/api/finance/subscriptions/<int:sid>", methods=["PATCH", "DELETE"])
def api_finance_modify_subscription(sid: int):
    init_db()
    if request.method == "DELETE":
        if not finance_delete_subscription(sid):
            return jsonify({"error": "subscription not found"}), 404
        return jsonify({"ok": True})
    data = request.get_json(force=True, silent=False) or {}
    updated, err = finance_patch_subscription(sid, data)
    if err == "subscription not found":
        return jsonify({"error": err}), 404
    if err is not None:
        return jsonify({"error": err}), 400
    return jsonify(updated)


@app.route("/api/finance/ocr", methods=["POST"])
def api_finance_ocr():
    init_db()
    if not finance_is_ocr_configured():
        return jsonify(
            {
                "error": "Gemini API key not configured",
                "hint": "set CEO_CONSOLE_GEMINI_API_KEY or GEMINI_API_KEY in env",
            }
        ), 503
    file = request.files.get("file")
    if file is None or not file.filename:
        return jsonify({"error": "file is required (multipart/form-data field \"file\")"}), 400
    content = file.read()
    if not content:
        return jsonify({"error": "file is empty"}), 400
    mime_type = (file.mimetype or "").lower() or "application/octet-stream"
    if mime_type not in OCR_SUPPORTED_MIME_TYPES:
        return jsonify(
            {
                "error": f"unsupported mime type: {mime_type}",
                "supported": sorted(OCR_SUPPORTED_MIME_TYPES),
            }
        ), 415
    result, err = finance_ocr_receipt(content, mime_type, file.filename)
    if err is not None:
        return jsonify({"error": err}), 502
    return jsonify(result)


@app.route("/api/finance/receipts/<path:name>", methods=["GET"])
def api_finance_receipt_file(name: str):
    # Resolve dynamically so tests can override RECEIPTS_DIR via monkeypatch.
    receipts_dir = _finance_mod.RECEIPTS_DIR
    safe_name = Path(name).name
    target = receipts_dir / safe_name
    if not target.exists() or not target.is_file():
        return jsonify({"error": "receipt not found"}), 404
    return send_from_directory(receipts_dir, safe_name)


@app.route("/api/finance/ocr/status", methods=["GET"])
def api_finance_ocr_status():
    return jsonify({"configured": finance_is_ocr_configured()})
