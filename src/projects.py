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
from .db import db_conn, init_db
from .finance import get_transactions_by_project
from .tasks import fetch_tasks, row_to_task


PROJECT_METADATA_FIELDS = {"client_name", "budget_cents", "status", "description"}
PROJECT_STATUSES = {"active", "completed", "paused"}


def row_to_project_metadata(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "client_name": row["client_name"] or "",
        "budget_cents": int(row["budget_cents"] or 0),
        "status": row["status"] or "active",
        "description": row["description"] or "",
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def get_project_metadata_map() -> dict[str, dict[str, Any]]:
    init_db()
    with closing(db_conn()) as conn:
        rows = conn.execute("SELECT * FROM projects").fetchall()
    return {row["name"]: row_to_project_metadata(row) for row in rows}


def get_project_metadata(name: str) -> dict[str, Any] | None:
    init_db()
    with closing(db_conn()) as conn:
        row = conn.execute("SELECT * FROM projects WHERE name = ?", (name,)).fetchone()
    return row_to_project_metadata(row) if row else None


def _coerce_budget_cents(raw: Any) -> int | None:
    if raw is None or raw == "":
        return 0
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return None


def update_project_metadata(name: str, payload: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    name_error = validate_project_name(name)
    if name_error:
        return None, name_error

    fields: dict[str, Any] = {}
    if "client_name" in payload:
        fields["client_name"] = str(payload.get("client_name") or "").strip()
    if "budget_cents" in payload:
        budget_cents = _coerce_budget_cents(payload.get("budget_cents"))
        if budget_cents is None:
            return None, "budget_cents must be an integer"
        fields["budget_cents"] = budget_cents
    elif "budget" in payload:
        budget_cents = _coerce_budget_cents(payload.get("budget"))
        if budget_cents is None:
            return None, "budget must be an integer"
        fields["budget_cents"] = budget_cents
    if "status" in payload:
        status = str(payload.get("status") or "").strip().lower()
        if status not in PROJECT_STATUSES:
            return None, f"status must be one of {sorted(PROJECT_STATUSES)}"
        fields["status"] = status
    if "description" in payload or "desc" in payload:
        fields["description"] = str(payload.get("description", payload.get("desc", "")) or "").strip()

    if not fields:
        return None, "no valid fields provided"

    ts = now_str()
    init_db()
    with closing(db_conn()) as conn:
        conn.execute(
            """
            INSERT INTO projects (name, client_name, budget_cents, status, description, created_at, updated_at)
            VALUES (?, '', 0, 'active', '', ?, ?)
            ON CONFLICT(name) DO NOTHING
            """,
            (name, ts, ts),
        )
        fields["updated_at"] = ts
        set_clause = ", ".join(f"{key} = ?" for key in fields)
        conn.execute(
            f"UPDATE projects SET {set_clause} WHERE name = ?",
            [*fields.values(), name],
        )
        conn.commit()
        row = conn.execute("SELECT * FROM projects WHERE name = ?", (name,)).fetchone()
    return row_to_project_metadata(row), None

def run_pm_command(args: list[str], input_text: str | None = None) -> subprocess.CompletedProcess:
    if not PM_SCRIPT.exists():
        raise FileNotFoundError(f"pm script not found: {PM_SCRIPT}")
    return subprocess.run(
        [str(PM_SCRIPT)] + args,
        input=input_text,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
    )


def run_git_command(project_path: Path, args: list[str]) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(project_path),
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=5,
        )
    except Exception as exc:
        return False, str(exc)
    output = (result.stdout or result.stderr or "").strip()
    return result.returncode == 0, output


def parse_checklist_progress(project_path: Path) -> dict[str, int]:
    checklist = project_path / "docs" / "执行清单.md"
    progress = {"total": 0, "done": 0}
    if not checklist.exists():
        return progress
    try:
        text = checklist.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return progress
    for line in text.splitlines():
        if re.search(r"^\s*[-*]\s+\[[ xX]\]", line):
            progress["total"] += 1
            if re.search(r"^\s*[-*]\s+\[[xX]\]", line):
                progress["done"] += 1
    return progress


def count_adr_files(project_path: Path) -> int:
    docs_dir = project_path / "docs"
    if not docs_dir.exists():
        return 0
    try:
        return sum(1 for p in docs_dir.rglob("ADR-*.md") if p.is_file())
    except OSError:
        return 0


def compute_governance_score(project_path: Path) -> dict[str, Any]:
    checklist = parse_checklist_progress(project_path)
    checklist_ratio = checklist["done"] / checklist["total"] if checklist["total"] else 0
    adr_count = count_adr_files(project_path)
    score = 0
    score += round(checklist_ratio * 45)
    score += min(20, adr_count * 5)
    score += 10 if (project_path / "CLAUDE.md").exists() else 0
    score += 8 if (project_path / ".cursorrules").exists() else 0
    score += 7 if (project_path / ".agent-coordinator").exists() else 0
    score += 10 if (project_path / ".git").exists() else 0
    if score >= 80:
        phase = "交付/维护"
    elif score >= 55:
        phase = "开发推进"
    elif score >= 30:
        phase = "治理补齐"
    else:
        phase = "孵化启动"
    return {
        "governance_score": min(100, score),
        "phase": phase,
        "adr_count": adr_count,
        "checklist_total": checklist["total"],
        "checklist_done": checklist["done"],
        "checklist_completion": round(checklist_ratio * 100),
    }


def inspect_repository(project: dict[str, Any], repo_path: Path | None = None, label: str | None = None) -> dict[str, Any]:
    path = repo_path or Path(project["path"])
    rel = ""
    if repo_path:
        try:
            rel = str(repo_path.relative_to(Path(project["path"])))
        except ValueError:
            rel = repo_path.name
    is_git = (path / ".git").exists()
    repo = {
        "name": label or project["name"],
        "project": project["name"],
        "relative_path": rel,
        "path": str(path),
        "is_git": is_git,
        "branch": None,
        "dirty": False,
        "changed_count": 0,
        "remote": None,
        "last_commit": None,
        "last_commit_at": None,
        "status": "未初始化",
        "error": None,
    }
    if not is_git:
        return repo

    ok, branch = run_git_command(path, ["rev-parse", "--abbrev-ref", "HEAD"])
    if ok:
        repo["branch"] = branch
    else:
        repo["error"] = branch

    ok, status = run_git_command(path, ["status", "--short"])
    if ok:
        changed = [line for line in status.splitlines() if line.strip()]
        repo["changed_count"] = len(changed)
        repo["dirty"] = bool(changed)
        repo["status"] = "有未提交变更" if changed else "干净"

    ok, remote = run_git_command(path, ["remote", "get-url", "origin"])
    if ok:
        repo["remote"] = remote

    ok, commit = run_git_command(path, ["log", "-1", "--pretty=format:%h|%ci|%s"])
    if ok and commit:
        parts = commit.split("|", 2)
        if len(parts) == 3:
            repo["last_commit"] = f"{parts[0]} {parts[2]}"
            repo["last_commit_at"] = parts[1]
    return repo


def find_project_repositories(project: dict[str, Any]) -> list[dict[str, Any]]:
    project_path = Path(project["path"])
    repos: list[dict[str, Any]] = []
    if (project_path / ".git").exists():
        repos.append(inspect_repository(project, project_path, project["name"]))

    try:
        candidates = sorted(project_path.rglob(".git"), key=lambda p: str(p))
    except OSError:
        candidates = []
    for git_dir in candidates:
        repo_path = git_dir.parent
        if repo_path == project_path:
            continue
        try:
            rel = str(repo_path.relative_to(project_path))
        except ValueError:
            rel = repo_path.name
        if rel.count(os.sep) > 3:
            continue
        repos.append(inspect_repository(project, repo_path, f"{project['name']}/{rel}"))

    if not repos:
        repos.append(inspect_repository(project, project_path, project["name"]))
    return repos


def resolve_repository_action_path(raw_path: Any) -> tuple[Path | None, str | None]:
    if not raw_path:
        return None, "repository path is required"
    company_dir, _ = resolve_company_dir()
    try:
        company_root = company_dir.resolve()
        repo_path = Path(str(raw_path)).expanduser().resolve()
        repo_path.relative_to(company_root)
    except (OSError, ValueError):
        return None, "repository path must be under company directory"
    if not repo_path.exists() or not repo_path.is_dir():
        return None, "repository path not found"
    return repo_path, None


def run_repository_action(repo_path: Path, action: str, data: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
    data = data or {}
    action = action.strip()
    if action == "init":
        if (repo_path / ".git").exists():
            return 200, {"ok": True, "action": action, "path": str(repo_path), "command": "git init", "output": "仓库已初始化"}
        ok, output = run_git_command(repo_path, ["init"])
        return (200 if ok else 400), {"ok": ok, "action": action, "path": str(repo_path), "command": "git init", "output": output or "无输出"}

    if not (repo_path / ".git").exists():
        return 400, {"error": "repository is not initialized"}

    commands = {
        "status": ["status", "--short", "--branch"],
        "diff": ["diff", "--stat"],
        "log": ["log", "-5", "--oneline", "--decorate"],
        "pull": ["pull", "--ff-only"],
        "stage_all": ["add", "-A"],
        "push": ["push"],
    }
    if action == "commit":
        message = str(data.get("message", "")).strip()
        if not message:
            return 400, {"error": "commit message is required"}
        commands[action] = ["commit", "-m", message]
    if action not in commands:
        return 400, {"error": "unsupported repository action"}
    args = commands[action]
    ok, output = run_git_command(repo_path, args)
    return (200 if ok else 400), {
        "ok": ok,
        "action": action,
        "path": str(repo_path),
        "command": "git " + " ".join(args),
        "output": output or "无输出",
    }


def list_projects() -> list[dict]:
    projects: list[dict] = []
    company_dir, _ = resolve_company_dir()
    metadata_by_name = get_project_metadata_map()
    if not company_dir.exists():
        return list(metadata_by_name.values())
    try:
        entries = sorted(company_dir.iterdir(), key=lambda x: x.name)
    except PermissionError:
        return list(metadata_by_name.values())
    for p in entries:
        if not p.is_dir() or p.name.startswith("."):
            continue
        base = {
            "name": p.name,
            "path": str(p),
            "has_ai_rule": (p / "CLAUDE.md").exists(),
            "has_cursorrules": (p / ".cursorrules").exists(),
            "has_coordinator": (p / ".agent-coordinator").exists(),
            "has_execution_checklist": (p / "docs" / "执行清单.md").exists(),
        }
        projects.append(base | metadata_by_name.get(p.name, {}) | compute_governance_score(p))
    filesystem_names = {project["name"] for project in projects}
    for name, metadata in sorted(metadata_by_name.items()):
        if name not in filesystem_names:
            projects.append(metadata | {"path": str(company_dir / name), "missing_on_disk": True})
    return projects


def list_archived_projects() -> list[str]:
    company_dir, _ = resolve_company_dir()
    archive_dir = company_dir / ".archive"
    if not archive_dir.exists():
        return []
    try:
        return sorted([p.name for p in archive_dir.iterdir() if p.is_dir()])
    except PermissionError:
        return []


def get_project_tasks(name: str) -> list[dict]:
    init_db()
    with closing(db_conn()) as conn:
        rows = fetch_tasks(conn, {"project": name, "order_by": "updated_at"})
    return [row_to_task(row) for row in rows]


def get_project_finance(name: str) -> dict:
    transactions = get_transactions_by_project(name)
    income_cents = sum(t["amount_cents"] for t in transactions if t["direction"] == "in")
    expense_cents = sum(t["amount_cents"] for t in transactions if t["direction"] == "out")
    return {
        "income_cents": income_cents,
        "expense_cents": expense_cents,
        "net_cents": income_cents - expense_cents,
        "transactions": transactions,
    }


def get_project_detail(name: str) -> dict | None:
    metadata = get_project_metadata(name)
    project = next((p for p in list_projects() if p["name"] == name), None)
    if project is None and metadata is None:
        return None
    detail = project or metadata or {"name": name}
    tasks = get_project_tasks(name)
    finance = get_project_finance(name)
    repositories = find_project_repositories(detail) if detail.get("path") else []
    last_commit_at = None
    for repo in repositories:
        candidate = repo.get("last_commit_at")
        if candidate and (last_commit_at is None or candidate > last_commit_at):
            last_commit_at = candidate
    return {
        **detail,
        "tasks": tasks,
        "task_count": len(tasks),
        "finance": finance,
        "repositories": repositories,
        "git": {
            "repositories": repositories,
            "repo_count": len(repositories),
            "dirty_count": sum(1 for repo in repositories if repo.get("dirty")),
            "last_commit_at": last_commit_at,
        },
    }
