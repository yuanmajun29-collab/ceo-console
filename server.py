#!/usr/bin/env python3
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

from flask import Flask, jsonify, render_template, request
from flask import Response


APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR / "data"
DB_PATH = DATA_DIR / "ceo_console.db"
SETTINGS_PATH = DATA_DIR / "settings.json"

SAFE_COMPANY_DIR = Path.home() / "company"
DESKTOP_COMPANY_DIR = Path.home() / "Desktop" / "company"
LEGACY_COMPANY_DIR = Path.home() / "公司根目录"
COMPANY_DIR = SAFE_COMPANY_DIR if SAFE_COMPANY_DIR.exists() else (DESKTOP_COMPANY_DIR if DESKTOP_COMPANY_DIR.exists() else LEGACY_COMPANY_DIR)
ARCHIVE_DIR = COMPANY_DIR / ".archive"
PM_SCRIPT = Path.home() / "ai-team-template" / "初始化脚本" / "pm"
ACP_AGENT_SCRIPT = COMPANY_DIR / "acp-agent"
ACP_STATUS_SCRIPT = COMPANY_DIR / "acp-all-status"
DEFAULT_RECHARGE_URLS = {
    "Claude Code": "https://console.anthropic.com/settings/billing",
    "Codex": "https://platform.openai.com/settings/organization/billing/overview",
    "Gemini": "https://ai.google.dev/gemini-api/docs/billing",
    "Antigravity": "https://antigravity.com/pricing",
    "Cursor": "https://cursor.com/pricing",
}
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5050
DEFAULT_DISPATCH_TIMEOUT_SECONDS = 1800

ALLOWED_STATUS = {"待分配", "AI执行中", "待人工审查", "已完成"}
ALLOWED_PRIORITY = {"P0", "P1", "P2"}
ALLOWED_AI = {"Antigravity", "Claude Code", "Cursor", "Codex", "Gemini", "Other"}
ALLOWED_EXEC_STATE = {"idle", "running", "succeeded", "failed", "unsupported"}
ALLOWED_TASK_TYPE = {
    "market_research",
    "architecture",
    "fullstack",
    "code_edit",
    "testing",
    "docs",
    "security_review",
    "quality_review",
    "delivery",
}
PROJECT_NAME_RE = re.compile(r"^[A-Za-z0-9._\-\u4e00-\u9fff]{1,80}$")
TASK_TYPE_TOOL_ROUTE = {
    "market_research": ("Gemini", "广域调研需要长上下文检索，使用 Gemini，但只输出结论摘要以控制 token。"),
    "architecture": ("Claude Code", "架构决策需要高质量推理，使用 Claude Code；先让 Codex/摘要层准备精简上下文。"),
    "fullstack": ("Antigravity", "独立全栈集成任务才启动 Antigravity，避免把小改动交给高上下文 agent。"),
    "code_edit": ("Codex", "局部代码编辑默认交给 Codex，使用锁定范围降低上下文 token。"),
    "testing": ("Codex", "测试验证和批量命令执行默认交给 Codex，避免调用长上下文工具。"),
    "docs": ("Codex", "文档、接口说明和交付材料默认交给 Codex，复用已有上下文摘要。"),
    "security_review": ("Gemini", "安全/风险面扫描使用 Gemini，但限制为摘要式审查，避免全量代码粘贴。"),
    "quality_review": ("Claude Code", "代码质量和架构一致性审查使用 Claude Code，仅传 diff/关键文件。"),
    "delivery": ("Codex", "交付包、变更说明和验收材料默认交给 Codex。"),
}
ACP_TOOL_TARGET = {
    "Cursor": "cursor",
    "Antigravity": "antigravity",
    "Claude Code": "claude",
    "Codex": "codex",
    "Gemini": "gemini",
}
TOOL_TOKEN_PROFILE = {
    "Codex": {
        "cost": 1,
        "tier": "low",
        "best_for": ["局部代码修改", "测试验证", "文档交付", "批量命令", "交付整理"],
        "avoid_for": ["大范围竞品调研", "需要产品/架构深推理的模糊任务"],
    },
    "Gemini": {
        "cost": 2,
        "tier": "medium",
        "best_for": ["市场调研", "安全面扫描", "大范围资料归纳", "跨文件风险发现"],
        "avoid_for": ["明确的小代码改动", "重复执行命令"],
    },
    "Claude Code": {
        "cost": 3,
        "tier": "high",
        "best_for": ["架构设计", "复杂方案权衡", "代码质量审查", "关键决策"],
        "avoid_for": ["机械批量修改", "低风险文档整理"],
    },
    "Antigravity": {
        "cost": 4,
        "tier": "highest",
        "best_for": ["端到端全栈功能", "跨前后端集成", "较完整的可运行交付"],
        "avoid_for": ["小 bug", "单文件改动", "单纯测试或文档"],
    },
    "Cursor": {
        "cost": 1,
        "tier": "human-in-loop",
        "best_for": ["人工精修", "可视化 IDE 微调", "CEO 亲自接管"],
        "avoid_for": ["后台无人值守调度"],
    },
}
TASK_TYPE_PIPELINE = {
    "market_research": ["Gemini", "Claude Code", "Codex"],
    "architecture": ["Codex", "Claude Code", "Codex"],
    "fullstack": ["Codex", "Antigravity", "Codex", "Claude Code"],
    "code_edit": ["Codex", "Cursor"],
    "testing": ["Codex"],
    "docs": ["Codex"],
    "security_review": ["Codex", "Gemini", "Codex"],
    "quality_review": ["Codex", "Claude Code"],
    "delivery": ["Codex"],
}

app = Flask(__name__)
_TOOL_STATUS_CACHE: dict[str, Any] = {"ts": None, "data": None}


@app.after_request
def add_no_cache_headers(resp: Response) -> Response:
    # Avoid stale frontend HTML/API cache that can leave dashboard stuck on
    # "加载中..." when browser serves old script/state.
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp


def is_dir_accessible(path: Path) -> bool:
    if not path.exists() or not path.is_dir():
        return False
    try:
        list(path.iterdir())
        return True
    except PermissionError:
        return False


def resolve_company_dir() -> tuple[Path, str]:
    if is_dir_accessible(SAFE_COMPANY_DIR):
        return SAFE_COMPANY_DIR, "safe_home_company"
    if is_dir_accessible(DESKTOP_COMPANY_DIR):
        return DESKTOP_COMPANY_DIR, "desktop"
    if is_dir_accessible(LEGACY_COMPANY_DIR):
        return LEGACY_COMPANY_DIR, "legacy"
    if SAFE_COMPANY_DIR.exists():
        return SAFE_COMPANY_DIR, "safe_permission_denied"
    if DESKTOP_COMPANY_DIR.exists():
        return DESKTOP_COMPANY_DIR, "desktop_permission_denied"
    return LEGACY_COMPANY_DIR, "unavailable"


def get_acp_scripts() -> dict[str, Any]:
    company_dir, _ = resolve_company_dir()
    agent = company_dir / "acp-agent"
    status = company_dir / "acp-all-status"
    return {
        "agent": {"path": str(agent), "exists": agent.exists(), "executable": os.access(agent, os.X_OK)},
        "status": {"path": str(status), "exists": status.exists(), "executable": os.access(status, os.X_OK)},
    }


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def parse_datetime_value(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.strptime(str(raw).strip()[:19], "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return None


def parse_due_at(raw: str | None) -> str | None:
    if not raw:
        return None
    return raw.strip() or None


def load_settings() -> dict[str, Any]:
    defaults = {
        "dispatch_timeout_seconds": DEFAULT_DISPATCH_TIMEOUT_SECONDS,
        "auto_route_new_tasks": True,
        "dashboard_refresh_seconds": 15,
        "default_task_type": "fullstack",
        "default_assignee_ai": "Other",
    }
    if not SETTINGS_PATH.exists():
        return defaults
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return defaults
    merged = defaults | {k: v for k, v in data.items() if k in defaults}
    return normalize_settings(merged)


def normalize_settings(data: dict[str, Any]) -> dict[str, Any]:
    settings = dict(data)
    try:
        settings["dispatch_timeout_seconds"] = int(settings.get("dispatch_timeout_seconds", DEFAULT_DISPATCH_TIMEOUT_SECONDS))
    except (TypeError, ValueError):
        settings["dispatch_timeout_seconds"] = DEFAULT_DISPATCH_TIMEOUT_SECONDS
    settings["dispatch_timeout_seconds"] = max(60, min(7200, settings["dispatch_timeout_seconds"]))

    try:
        settings["dashboard_refresh_seconds"] = int(settings.get("dashboard_refresh_seconds", 15))
    except (TypeError, ValueError):
        settings["dashboard_refresh_seconds"] = 15
    settings["dashboard_refresh_seconds"] = max(5, min(300, settings["dashboard_refresh_seconds"]))

    settings["auto_route_new_tasks"] = bool(settings.get("auto_route_new_tasks", True))
    settings["default_task_type"] = normalize_task_type(settings.get("default_task_type", "fullstack"))
    default_ai = str(settings.get("default_assignee_ai", "Other")).strip()
    settings["default_assignee_ai"] = default_ai if default_ai in ALLOWED_AI else "Other"
    return settings


def save_settings(data: dict[str, Any]) -> dict[str, Any]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    settings = normalize_settings(load_settings() | data)
    SETTINGS_PATH.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
    return settings


def validate_project_name(name: str) -> str | None:
    if not name:
        return "项目名不能为空"
    if "/" in name or "\\" in name or name in {".", ".."}:
        return "项目名不能包含路径分隔符"
    if not PROJECT_NAME_RE.fullmatch(name):
        return "项目名仅支持中文、英文、数字、点、下划线和短横线，长度 1-80"
    return None


def normalize_task_type(value: Any) -> str:
    task_type = str(value or "fullstack").strip()
    return task_type if task_type in ALLOWED_TASK_TYPE else "fullstack"


def get_configured_host() -> str:
    return os.environ.get("CEO_CONSOLE_HOST", DEFAULT_HOST).strip() or DEFAULT_HOST


def get_configured_port() -> int:
    raw = os.environ.get("CEO_CONSOLE_PORT", str(DEFAULT_PORT)).strip()
    try:
        port = int(raw)
    except ValueError:
        return DEFAULT_PORT
    return port if 1 <= port <= 65535 else DEFAULT_PORT


def get_dispatch_timeout_seconds() -> int:
    saved = load_settings().get("dispatch_timeout_seconds")
    if saved:
        try:
            return max(60, int(saved))
        except (TypeError, ValueError):
            pass
    raw = os.environ.get("CEO_CONSOLE_DISPATCH_TIMEOUT_SECONDS", str(DEFAULT_DISPATCH_TIMEOUT_SECONDS)).strip()
    try:
        timeout = int(raw)
    except ValueError:
        return DEFAULT_DISPATCH_TIMEOUT_SECONDS
    return max(60, timeout)


def ensure_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


def init_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                project TEXT NOT NULL,
                assignee_ai TEXT NOT NULL,
                status TEXT NOT NULL,
                priority TEXT NOT NULL,
                due_at TEXT,
                acceptance_criteria TEXT,
                notes TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        ensure_column(conn, "tasks", "execution_state", "execution_state TEXT DEFAULT 'idle'")
        ensure_column(conn, "tasks", "execution_tool", "execution_tool TEXT")
        ensure_column(conn, "tasks", "execution_command", "execution_command TEXT")
        ensure_column(conn, "tasks", "execution_output", "execution_output TEXT")
        ensure_column(conn, "tasks", "execution_error", "execution_error TEXT")
        ensure_column(conn, "tasks", "execution_progress", "execution_progress TEXT")
        ensure_column(conn, "tasks", "execution_started_at", "execution_started_at TEXT")
        ensure_column(conn, "tasks", "execution_finished_at", "execution_finished_at TEXT")
        ensure_column(conn, "tasks", "estimated_finish_at", "estimated_finish_at TEXT")
        ensure_column(conn, "tasks", "review_result", "review_result TEXT")
        ensure_column(conn, "tasks", "review_comment", "review_comment TEXT")
        ensure_column(conn, "tasks", "reviewed_at", "reviewed_at TEXT")
        ensure_column(conn, "tasks", "task_type", "task_type TEXT DEFAULT 'fullstack'")
        ensure_column(conn, "tasks", "ai_instruction", "ai_instruction TEXT")
        ensure_column(conn, "tasks", "locked_scope", "locked_scope TEXT")
        ensure_column(conn, "tasks", "expected_output", "expected_output TEXT")
        ensure_column(conn, "tasks", "verification_command", "verification_command TEXT")
        ensure_column(conn, "tasks", "routing_reason", "routing_reason TEXT")
        ensure_column(conn, "tasks", "delivery_evidence", "delivery_evidence TEXT")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS decision_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project TEXT NOT NULL,
                decision TEXT NOT NULL,
                context TEXT,
                reason TEXT,
                impact TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.commit()


def db_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


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
    if not company_dir.exists():
        return projects
    try:
        entries = sorted(company_dir.iterdir(), key=lambda x: x.name)
    except PermissionError:
        return projects
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
        projects.append(base | compute_governance_score(p))
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
        if any(key in line for key in ["开始执行", "进程已启动", "执行完成", "人工审查"]):
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


def tool_candidates(tool_name: str) -> list[str]:
    mapping = {
        "Claude Code": ["claude"],
        "Codex": ["codex"],
        "Gemini": ["gemini"],
        # For headless dispatch we must prefer OpenClaw CLI over GUI launcher.
        "Antigravity": ["openclaw", "antigravity"],
        "Cursor": ["cursor", "cursor-agent"],
    }
    return mapping.get(tool_name, [])


def resolve_tool_command(tool_name: str) -> str | None:
    extra_dirs = [
        "/opt/homebrew/bin",
        "/usr/local/bin",
        "/usr/bin",
        "/bin",
        str(Path.home() / ".antigravity" / "antigravity" / "bin"),
        str(Path.home() / "Library" / "Python" / "3.9" / "bin"),
    ]
    for c in tool_candidates(tool_name):
        found = shutil.which(c)
        if found:
            return found
        for d in extra_dirs:
            cand = Path(d) / c
            if cand.exists() and os.access(cand, os.X_OK):
                return str(cand)
    return None


def build_tool_run_command(tool_name: str, prompt: str) -> tuple[list[str] | None, str | None]:
    acp_scripts = get_acp_scripts()
    acp_agent = acp_scripts["agent"]
    acp_target = ACP_TOOL_TARGET.get(tool_name)
    if acp_target and acp_agent["exists"] and acp_agent["executable"]:
        agent_path = acp_agent["path"]
        if tool_name == "Claude Code":
            return [agent_path, acp_target, "-p", "--output-format", "text", prompt], None
        if tool_name == "Gemini":
            return [agent_path, acp_target, prompt], None
        if tool_name == "Codex":
            return [
                agent_path,
                acp_target,
                "exec",
                "--skip-git-repo-check",
                "--sandbox",
                "workspace-write",
                "--color",
                "never",
                prompt,
            ], None
        if tool_name == "Antigravity":
            return [agent_path, acp_target, "agent", "--local", "--agent", "main", "--message", prompt, "--json"], None
        if tool_name == "Cursor":
            return None, "Cursor ACP 当前会打开 IDE 交互窗口，不适合后台无头调度。请改用 Claude/Gemini/Antigravity/Codex。"

    cmd_path = resolve_tool_command(tool_name)
    if not cmd_path:
        return None, f"未找到可执行命令候选：{tool_candidates(tool_name)}"

    # Prefer non-interactive execution where supported.
    if tool_name == "Claude Code":
        return [cmd_path, "-p", "--output-format", "text", prompt], None
    if tool_name == "Gemini":
        return [cmd_path, "-p", prompt], None
    if tool_name == "Antigravity":
        # Antigravity/OpenClaw supports headless agent turns via local mode.
        # Force explicit agent to avoid "choose a session" interactive prompt.
        return [cmd_path, "agent", "--local", "--agent", "main", "--message", prompt, "--json"], None
    if tool_name == "Codex":
        # Use the non-interactive runner so backend dispatch does not require a TTY.
        return [cmd_path, "exec", "--skip-git-repo-check", "--sandbox", "workspace-write", "--color", "never", prompt], None
    if tool_name == "Cursor":
        return None, "Cursor CLI 当前用于打开IDE窗口，不支持稳定的无头自动执行。请改用 Claude/Gemini/Antigravity/Codex。"

    return [cmd_path, prompt], None


def pick_fallback_tool(preferred_tools: list[str] | None = None) -> tuple[str | None, str | None]:
    ordered = preferred_tools or ["Claude Code", "Gemini"]
    status = get_tools_status_cached()
    for tool in ordered:
        info = status.get(tool) or {}
        if info.get("available") and info.get("runnable"):
            return tool, None
    return None, "未找到可自动调度的后备工具（需要可运行的 Claude Code 或 Gemini）"


def check_command_runnable(path: str) -> tuple[bool, str | None]:
    try:
        # Quick smoke check: many CLIs support --help without side effects.
        res = subprocess.run(
            [path, "--help"],
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=8,
        )
        if res.returncode == 0:
            return True, None
        err = (res.stderr or res.stdout or "").strip()
        return False, err[:400]
    except Exception as exc:
        return False, str(exc)


def quota_env_key(tool_name: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", tool_name.upper()).strip("_")


def get_recharge_url(tool_name: str, raw: dict[str, Any] | None = None) -> str | None:
    raw_url = (raw or {}).get("recharge_url")
    if raw_url:
        return str(raw_url)
    key = quota_env_key(tool_name)
    env_url = os.getenv(f"CEO_CONSOLE_RECHARGE_{key}_URL")
    if env_url:
        return env_url
    return DEFAULT_RECHARGE_URLS.get(tool_name)


def normalize_quota(tool_name: str, raw: dict[str, Any] | None, source: str) -> dict[str, Any]:
    if not raw:
        return {
            "available": False,
            "source": "not_configured",
            "label": "未接入",
            "remaining": None,
            "limit": None,
            "unit": "tokens",
            "percent": None,
            "reset_at": None,
            "recharge_url": get_recharge_url(tool_name),
        }
    unit = str(raw.get("unit") or "tokens")
    remaining = raw.get("remaining")
    limit = raw.get("limit")
    try:
        remaining_num = float(remaining) if remaining not in (None, "") else None
    except (TypeError, ValueError):
        remaining_num = None
    try:
        limit_num = float(limit) if limit not in (None, "") else None
    except (TypeError, ValueError):
        limit_num = None
    percent = None
    if remaining_num is not None and limit_num and limit_num > 0:
        percent = max(0, min(100, round((remaining_num / limit_num) * 100)))
    label = str(raw.get("label") or "").strip()
    if not label:
        if remaining_num is not None and limit_num:
            label = f"{remaining_num:g}/{limit_num:g} {unit}"
        elif remaining_num is not None:
            label = f"{remaining_num:g} {unit}"
        else:
            label = "待同步"
    return {
        "available": True,
        "source": source,
        "label": label,
        "remaining": remaining_num,
        "limit": limit_num,
        "unit": unit,
        "percent": percent,
        "reset_at": raw.get("reset_at"),
        "recharge_url": get_recharge_url(tool_name, raw),
        "tool": tool_name,
    }


def get_tool_quota(tool_name: str) -> dict[str, Any]:
    quota_json = os.getenv("CEO_CONSOLE_AI_QUOTA_JSON", "").strip()
    if quota_json:
        try:
            quota_data = json.loads(quota_json)
            raw = quota_data.get(tool_name) or quota_data.get(quota_env_key(tool_name))
            if isinstance(raw, dict):
                return normalize_quota(tool_name, raw, "env_json")
        except json.JSONDecodeError:
            return {
                "available": False,
                "source": "env_json_error",
                "label": "配置错误",
                "remaining": None,
                "limit": None,
                "unit": "tokens",
                "percent": None,
                "reset_at": None,
                "recharge_url": get_recharge_url(tool_name),
            }

    key = quota_env_key(tool_name)
    raw = {
        "remaining": os.getenv(f"CEO_CONSOLE_QUOTA_{key}_REMAINING"),
        "limit": os.getenv(f"CEO_CONSOLE_QUOTA_{key}_LIMIT"),
        "unit": os.getenv(f"CEO_CONSOLE_QUOTA_{key}_UNIT") or "tokens",
        "reset_at": os.getenv(f"CEO_CONSOLE_QUOTA_{key}_RESET_AT"),
        "label": os.getenv(f"CEO_CONSOLE_QUOTA_{key}_LABEL"),
        "recharge_url": os.getenv(f"CEO_CONSOLE_RECHARGE_{key}_URL"),
    }
    if any(raw.get(field) for field in ["remaining", "limit", "reset_at", "label"]):
        return normalize_quota(tool_name, raw, "env")
    return normalize_quota(tool_name, None, "not_configured")


def get_tools_status_cached() -> dict[str, Any]:
    now = datetime.now()
    ts = _TOOL_STATUS_CACHE.get("ts")
    if ts and _TOOL_STATUS_CACHE.get("data") is not None:
        if (now - ts).total_seconds() < 60:
            return _TOOL_STATUS_CACHE["data"]

    headless_support = {
        "Cursor": False,
        "Antigravity": True,
        "Claude Code": True,
        "Codex": True,
        "Gemini": True,
    }
    data: dict[str, Any] = {}
    acp_scripts = get_acp_scripts()
    for tool in ["Cursor", "Antigravity", "Claude Code", "Codex", "Gemini"]:
        command = resolve_tool_command(tool)
        available = command is not None
        runnable = False
        reason = None
        if available and command and headless_support.get(tool, True):
            runnable, reason = check_command_runnable(command)
        elif available and not headless_support.get(tool, True):
            runnable = False
            reason = "该工具当前仅支持交互模式，不支持后台无头自动执行。"
        data[tool] = {
            "available": available,
            "runnable": runnable if available else False,
            "command": command,
            "candidates": tool_candidates(tool),
            "reason": reason,
            "quota": get_tool_quota(tool),
            "acp_target": ACP_TOOL_TARGET.get(tool),
            "acp_enabled": bool(acp_scripts["agent"]["exists"] and acp_scripts["agent"]["executable"] and ACP_TOOL_TARGET.get(tool)),
        }

    _TOOL_STATUS_CACHE["ts"] = now
    _TOOL_STATUS_CACHE["data"] = data
    return data


def estimate_context_size(title: str = "", notes: str = "", locked_scope: str = "", acceptance: str = "") -> dict[str, Any]:
    text = f"{title}\n{notes}\n{locked_scope}\n{acceptance}"
    char_count = len(text)
    scope_count = len([part for part in re.split(r"[,，\n\s]+", locked_scope or "") if part.strip()])
    if char_count <= 600 and scope_count <= 2:
        level = "small"
        label = "小上下文"
    elif char_count <= 2200 and scope_count <= 8:
        level = "medium"
        label = "中上下文"
    else:
        level = "large"
        label = "大上下文"
    return {"level": level, "label": label, "char_count": char_count, "scope_count": scope_count}


def infer_project_profile(project: str = "", locked_scope: str = "") -> dict[str, Any]:
    company_dir, _ = resolve_company_dir()
    project_path = company_dir / project if project else None
    scope_text = locked_scope.lower()
    signals: set[str] = set()
    domains: set[str] = set()
    scope_domains: set[str] = set()

    def mark(domain: str, signal: str, from_scope: bool = False) -> None:
        domains.add(domain)
        signals.add(signal)
        if from_scope:
            scope_domains.add(domain)

    if any(k in scope_text for k in ["frontend", "web", ".vue", ".tsx", ".jsx", "package.json"]):
        mark("frontend", "locked_scope", True)
    if any(k in scope_text for k in ["backend", "server", ".py", ".java", ".kt", "api"]):
        mark("backend", "locked_scope", True)
    if any(k in scope_text for k in ["android", ".kt", "gradle"]):
        mark("android", "locked_scope", True)
    if any(k in scope_text for k in ["docker", "deploy", "k8s", "systemd", "nginx"]):
        mark("devops", "locked_scope", True)
    if any(k in scope_text for k in ["gate", "edge", "mqtt", "wavegate"]):
        mark("edge", "locked_scope", True)
    if any(k in scope_text for k in ["docs", "adr", ".md"]):
        mark("docs", "locked_scope", True)

    if project_path and project_path.exists():
        checks = [
            ("frontend", "package.json", project_path / "package.json"),
            ("frontend", "frontend/", project_path / "frontend"),
            ("frontend", "src/web", project_path / "src" / "web"),
            ("backend", "backend/", project_path / "backend"),
            ("backend", "java/", project_path / "java"),
            ("backend", "pyproject.toml", project_path / "pyproject.toml"),
            ("android", "android/", project_path / "android"),
            ("devops", "docker-compose.yml", project_path / "docker-compose.yml"),
            ("devops", "deploy/", project_path / "deploy"),
            ("edge", "src/gate", project_path / "src" / "gate"),
            ("docs", "docs/", project_path / "docs"),
        ]
        for domain, signal, path in checks:
            if path.exists():
                mark(domain, signal)

    nature_domains = scope_domains or domains
    if "edge" in nature_domains:
        archetype = "edge"
    elif "android" in nature_domains:
        archetype = "mobile"
    elif "devops" in nature_domains:
        archetype = "devops"
    elif {"frontend", "backend"}.issubset(nature_domains):
        archetype = "fullstack"
    elif "frontend" in nature_domains:
        archetype = "frontend"
    elif "backend" in nature_domains:
        archetype = "backend"
    elif "docs" in nature_domains:
        archetype = "docs"
    else:
        archetype = "unknown"
    return {
        "project": project or None,
        "archetype": archetype,
        "domains": sorted(domains),
        "scope_domains": sorted(scope_domains),
        "signals": sorted(signals),
    }


def adapt_pipeline_for_project(
    task_type: str,
    preferred_tool: str,
    pipeline: list[str],
    project_profile: dict[str, Any],
    context_level: str,
) -> tuple[str, list[str], str | None]:
    archetype = project_profile.get("archetype")
    domains = set(project_profile.get("domains") or [])
    note = None

    if task_type == "fullstack":
        if archetype == "fullstack":
            preferred_tool = "Antigravity"
            pipeline = ["Codex", "Antigravity", "Codex", "Claude Code"]
            note = "项目同时包含前后端，适合 Antigravity 做端到端集成，Codex 负责压缩与验收。"
        elif archetype in {"backend", "edge", "mobile", "devops"} or (domains & {"backend", "edge", "android", "devops"} and "frontend" not in domains):
            preferred_tool = "Codex"
            pipeline = ["Codex", "Claude Code"]
            note = "项目更偏后端/边缘/移动/部署，先用 Codex 做局部实现，复杂设计再交 Claude Code 复核，避免启动全栈 agent。"

    if task_type in {"code_edit", "testing", "docs", "delivery"}:
        preferred_tool = "Codex"
        pipeline = ["Codex", "Cursor"] if task_type == "code_edit" and context_level == "small" else ["Codex"]
        note = "任务属于明确执行型工作，Codex 成本最低；Cursor 仅保留为人工精修入口。"

    if task_type == "security_review" and domains & {"edge", "devops", "backend"}:
        preferred_tool = "Gemini"
        pipeline = ["Codex", "Gemini", "Codex"]
        note = "项目包含后端/边缘/部署风险面，先由 Codex 汇总范围，再用 Gemini 做广域安全扫描。"

    if task_type in {"architecture", "quality_review"}:
        preferred_tool = "Claude Code"
        pipeline = ["Codex", "Claude Code", "Codex"] if task_type == "architecture" else ["Codex", "Claude Code"]
        note = "架构/质量判断更适合 Claude Code，但先由 Codex 准备精简上下文。"

    return preferred_tool, pipeline, note


def token_optimized_pipeline(
    task_type: str | None,
    title: str = "",
    notes: str = "",
    locked_scope: str = "",
    acceptance: str = "",
    project: str = "",
) -> dict[str, Any]:
    normalized = normalize_task_type(task_type)
    context = estimate_context_size(title, notes, locked_scope, acceptance)
    project_profile = infer_project_profile(project, locked_scope)
    preferred_tool, reason = recommend_tool_for_task(normalized, title, f"{notes} {acceptance}")
    pipeline = list(TASK_TYPE_PIPELINE.get(normalized, ["Codex"]))
    preferred_tool, pipeline, project_note = adapt_pipeline_for_project(
        normalized, preferred_tool, pipeline, project_profile, context["level"]
    )
    if project_note:
        reason = project_note

    if context["level"] == "small" and preferred_tool != "Codex" and normalized in {"fullstack", "quality_review", "security_review"}:
        pipeline = ["Codex", preferred_tool] if preferred_tool != "Codex" else ["Codex"]
        reason = f"任务上下文较小，先用 Codex 做最小变更/摘要，再按需升级到 {preferred_tool}。"
    elif context["level"] == "large" and pipeline[0] != "Codex":
        pipeline.insert(0, "Codex")
        reason = f"任务上下文较大，先用 Codex 生成摘要/锁定范围，再调用 {preferred_tool}，降低后续 token。"

    deduped: list[str] = []
    for tool in pipeline:
        if not deduped or deduped[-1] != tool:
            deduped.append(tool)

    return {
        "task_type": normalized,
        "primary_tool": preferred_tool,
        "reason": reason,
        "context": context,
        "project_profile": project_profile,
        "pipeline": [
            {
                "tool": tool,
                "acp_target": ACP_TOOL_TARGET.get(tool),
                "token_cost": TOOL_TOKEN_PROFILE.get(tool, {}).get("cost"),
                "tier": TOOL_TOKEN_PROFILE.get(tool, {}).get("tier"),
                "role": pipeline_role(tool, idx, preferred_tool),
            }
            for idx, tool in enumerate(deduped)
        ],
        "token_policy": [
            "先摘要、后执行：大上下文任务先由 Codex 提炼范围和验收点。",
            "先局部、后全栈：单文件/小范围改动不启动 Antigravity。",
            "工具擅长点优先：架构交给 Claude，广域调研/安全交给 Gemini，局部执行交给 Codex，全栈集成交给 Antigravity。",
            "项目性质优先：根据前端/后端/移动/边缘/部署/文档画像调整链路。",
            "先机器、后人工：Cursor 作为人工精修入口，不做后台调度。",
            "只传必要上下文：优先传 diff、锁定文件、执行清单和 ADR 摘要。",
        ],
    }


def pipeline_role(tool: str, index: int, primary_tool: str) -> str:
    if index == 0 and tool == "Codex" and primary_tool != "Codex":
        return "上下文压缩/任务拆解"
    if tool == primary_tool:
        return "主执行"
    if tool == "Cursor":
        return "人工精修"
    if tool == "Claude Code":
        return "架构/质量复核"
    if tool == "Gemini":
        return "广域调研/安全扫描"
    if tool == "Antigravity":
        return "端到端集成"
    return "执行/验证"


def recommend_tool_for_task(task_type: str | None, title: str = "", notes: str = "") -> tuple[str, str]:
    normalized = normalize_task_type(task_type)
    tool, reason = TASK_TYPE_TOOL_ROUTE.get(normalized, TASK_TYPE_TOOL_ROUTE["fullstack"])
    text = f"{title} {notes}".lower()
    if any(k in text for k in ["安全", "security", "漏洞", "权限"]):
        return "Gemini", "任务内容包含安全/风险关键词，优先使用 Gemini。"
    if any(k in text for k in ["架构", "schema", "数据模型", "architecture"]):
        return "Claude Code", "任务内容包含架构/数据模型关键词，优先使用 Claude Code。"
    if any(k in text for k in ["测试", "test", "文档", "docs", "swagger", "交付"]):
        return "Codex", "任务内容偏测试/文档/交付，优先使用 Codex。"
    return tool, reason


def launchd_service_status() -> dict[str, Any]:
    label = "com.oneperson.ceo-console"
    try:
        result = subprocess.run(
            ["launchctl", "list"],
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=10,
        )
        if result.returncode != 0:
            return {"label": label, "loaded": False, "raw": result.stderr.strip()}
        line = next((ln for ln in result.stdout.splitlines() if label in ln), "")
        if not line:
            return {"label": label, "loaded": False, "raw": ""}
        parts = line.split()
        pid = parts[0] if len(parts) >= 1 else "-"
        exit_code = parts[1] if len(parts) >= 2 else "-"
        return {"label": label, "loaded": True, "pid": pid, "exit_code": exit_code, "raw": line}
    except Exception as exc:
        return {"label": label, "loaded": False, "error": str(exc)}


def build_dispatch_prompt(task: sqlite3.Row) -> str:
    instruction = task["ai_instruction"] or f"完成任务：{task['title']}"
    return (
        f"你是项目执行智能体。请在项目 {task['project']} 中完成任务：{task['title']}。\n"
        f"任务类型：{task['task_type'] or 'fullstack'}\n"
        f"优先级：{task['priority']}\n"
        f"给AI的指令：{instruction}\n"
        f"验收标准：{task['acceptance_criteria'] or '未提供'}\n"
        f"锁定文件/模块：{task['locked_scope'] or '未指定'}\n"
        f"预期产物：{task['expected_output'] or '未指定'}\n"
        f"验证命令：{task['verification_command'] or '未指定'}\n"
        f"备注：{task['notes'] or '无'}\n"
        "要求：先分析后实施；不得修改锁定范围之外的无关文件；完成后给出变更说明、验证结果和交付证据。"
    )


def set_task_execution_state(task_id: int, state: str, **kwargs: Any) -> None:
    if state not in ALLOWED_EXEC_STATE:
        state = "failed"
    fields = {"execution_state": state, "updated_at": now_str()}
    fields.update(kwargs)
    set_clause = ", ".join([f"{k} = ?" for k in fields.keys()])
    values = list(fields.values()) + [task_id]
    with closing(db_conn()) as conn:
        conn.execute(f"UPDATE tasks SET {set_clause} WHERE id = ?", values)
        conn.commit()


def append_task_progress(task_id: int, message: str) -> None:
    ts = now_str()
    with closing(db_conn()) as conn:
        row = conn.execute("SELECT execution_progress FROM tasks WHERE id = ?", (task_id,)).fetchone()
        old = (row["execution_progress"] if row else "") or ""
        line = f"[{ts}] {message}"
        merged = f"{old}\n{line}".strip() if old else line
        if len(merged) > 8000:
            merged = merged[-8000:]
        conn.execute(
            "UPDATE tasks SET execution_progress = ?, updated_at = ? WHERE id = ?",
            (merged, ts, task_id),
        )
        conn.commit()


def read_file_tail(path: Path, max_chars: int = 12000) -> str:
    if not path.exists():
        return ""
    max_bytes = max_chars * 4
    with path.open("rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        f.seek(max(0, size - max_bytes), os.SEEK_SET)
        data = f.read()
    return data.decode("utf-8", errors="replace")[-max_chars:]


def latest_task_log_path(task_id: int) -> Path | None:
    logs_dir = DATA_DIR / "run-logs"
    try:
        matches = sorted(logs_dir.glob(f"task-{task_id}-*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        return None
    return matches[0] if matches else None


def log_indicates_success(text: str) -> bool:
    if not text:
        return False
    success_markers = [
        '"result": "success"',
        '"result":"success"',
        '"stopReason": "stop"',
        '"stopReason":"stop"',
        "执行完成：成功",
        "finalAssistantVisibleText",
    ]
    return any(marker in text for marker in success_markers)


def dispatch_task_worker(task_id: int) -> None:
    init_db()
    with closing(db_conn()) as conn:
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if row is None:
        return

    requested_tool = row["assignee_ai"]
    tool = requested_tool
    prompt = build_dispatch_prompt(row)
    append_task_progress(task_id, f"任务进入调度队列，请求工具：{requested_tool}")
    cmd, build_err = build_tool_run_command(tool, prompt)

    # Auto-fallback: keep dispatch running even if chosen tool is not headless-runnable.
    if build_err:
        fallback_tool, fallback_err = pick_fallback_tool()
        if fallback_tool:
            tool = fallback_tool
            cmd, build_err = build_tool_run_command(tool, prompt)
            if not build_err:
                append_task_progress(task_id, f"工具不可调度，自动回退到：{tool}")
                set_task_execution_state(
                    task_id,
                    "idle",
                    execution_error=f"已自动回退：请求工具 {requested_tool} 不可调度，改用 {tool}",
                )
        else:
            build_err = f"{build_err}；{fallback_err}"

    if build_err:
        append_task_progress(task_id, f"构建执行命令失败：{build_err}")
        set_task_execution_state(
            task_id,
            "unsupported",
            execution_tool=requested_tool,
            execution_error=build_err,
            execution_finished_at=now_str(),
        )
        return

    set_task_execution_state(
        task_id,
        "running",
        execution_tool=f"{requested_tool}->{tool}" if requested_tool != tool else tool,
        execution_command=" ".join(cmd),
        execution_started_at=now_str(),
        execution_error=None,
        execution_output=None,
        execution_progress=None,
    )
    append_task_progress(task_id, f"开始执行：{' '.join(cmd)}")
    with closing(db_conn()) as conn:
        conn.execute("UPDATE tasks SET status = 'AI执行中', updated_at = ? WHERE id = ?", (now_str(), task_id))
        conn.commit()

    company_dir, _ = resolve_company_dir()
    project_dir = company_dir / row["project"]
    logs_dir = DATA_DIR / "run-logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / f"task-{task_id}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.log"
    try:
        run_cwd = str(project_dir) if project_dir.exists() else str(company_dir)
        last_output = ""
        timed_out = False
        with log_path.open("w", encoding="utf-8", errors="replace") as log_file:
            proc = subprocess.Popen(
                cmd,
                cwd=run_cwd,
                text=True,
                encoding="utf-8",
                errors="replace",
                stdout=log_file,
                stderr=subprocess.STDOUT,
            )
            append_task_progress(task_id, f"进程已启动（PID={proc.pid}）")
            started = time.monotonic()
            last_progress_at = started
            while True:
                rc = proc.poll()
                current_output = read_file_tail(log_path, max_chars=12000)
                if current_output != last_output:
                    set_task_execution_state(task_id, "running", execution_output=current_output)
                    last_output = current_output
                now_monotonic = time.monotonic()
                if now_monotonic - last_progress_at >= 10:
                    append_task_progress(
                        task_id,
                        f"执行中：已运行 {int(now_monotonic - started)}s，日志长度 {len(current_output)} 字符",
                    )
                    last_progress_at = now_monotonic
                if rc is not None:
                    break
                if now_monotonic - started > get_dispatch_timeout_seconds():
                    timed_out = True
                    proc.kill()
                    proc.wait(timeout=5)
                    break
                time.sleep(2)
            return_code = proc.returncode

        final_output = read_file_tail(log_path, max_chars=12000)
        if timed_out:
            append_task_progress(task_id, "执行超时，已终止进程")
            set_task_execution_state(
                task_id,
                "failed",
                execution_output=final_output,
                execution_error=f"执行超时（{get_dispatch_timeout_seconds()}秒），日志文件：{log_path}",
                execution_finished_at=now_str(),
            )
            return

        if return_code == 0:
            append_task_progress(task_id, "执行完成：成功")
            set_task_execution_state(
                task_id,
                "succeeded",
                execution_output=final_output,
                execution_error=None,
                execution_finished_at=now_str(),
            )
            with closing(db_conn()) as conn:
                conn.execute("UPDATE tasks SET status = '待人工审查', updated_at = ? WHERE id = ?", (now_str(), task_id))
                conn.commit()
        else:
            append_task_progress(task_id, f"执行完成：失败（退出码 {return_code}）")
            set_task_execution_state(
                task_id,
                "failed",
                execution_output=final_output,
                execution_error=f"命令退出码 {return_code}，日志文件：{log_path}",
                execution_finished_at=now_str(),
            )
    except Exception as exc:
        append_task_progress(task_id, f"执行异常：{exc}")
        set_task_execution_state(
            task_id,
            "failed",
            execution_error=str(exc)[:4000],
            execution_finished_at=now_str(),
        )


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


if __name__ == "__main__":
    init_db()
    debug = os.environ.get("CEO_CONSOLE_DEBUG", "0") == "1"
    app.run(host=get_configured_host(), port=get_configured_port(), debug=debug)
