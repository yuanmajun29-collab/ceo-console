#!/usr/bin/env python3
"""ceo-console – Flask backend for task management.

This module provides:
- Flask routes for project and task CRUD operations.
- SQLite persistence of tasks.
- Integration with external AI command‑line tools (Antigravity, Claude, Gemini, etc.).
- Optional launchd service status checks on macOS.

All business logic is kept in this file for simplicity; the Celery integration
moves the heavy task execution to an asynchronous worker (see `tasks.py`).
"""

from __future__ import annotations

# ------------------------------------------------------------
# Standard library imports
# ------------------------------------------------------------
import os
import shutil
import sqlite3
import subprocess
import threading
import time
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

# ------------------------------------------------------------
# Flask imports
# ------------------------------------------------------------
from flask import Flask, jsonify, render_template, request, Response

# ------------------------------------------------------------
# Global constants and configuration
# ------------------------------------------------------------
APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR / "data"
DB_PATH = DATA_DIR / "ceo_console.db"

SAFE_COMPANY_DIR = Path.home() / "company"
DESKTOP_COMPANY_DIR = Path.home() / "Desktop" / "company"
LEGACY_COMPANY_DIR = Path.home() / "公司根目录"
COMPANY_DIR = SAFE_COMPANY_DIR if SAFE_COMPANY_DIR.exists() else (
    DESKTOP_COMPANY_DIR if DESKTOP_COMPANY_DIR.exists() else LEGACY_COMPANY_DIR
)
ARCHIVE_DIR = COMPANY_DIR / ".archive"
PM_SCRIPT = Path.home() / "ai-team-template" / "初始化脚本" / "pm"

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5050
DEFAULT_DISPATCH_TIMEOUT_SECONDS = 1800

ALLOWED_STATUS = {"待分配", "AI执行中", "待人工审查", "已完成"}
ALLOWED_PRIORITY = {"P0", "P1", "P2"}
ALLOWED_AI = {"Antigravity", "Claude Code", "Cursor", "Codex", "Gemini", "Other"}
ALLOWED_EXEC_STATE = {"idle", "running", "succeeded", "failed", "unsupported"}

app = Flask(__name__)
_TOOL_STATUS_CACHE: dict[str, Any] = {"ts": None, "data": None}

# ------------------------------------------------------------
# Flask response post‑processing – prevent browser caching
# ------------------------------------------------------------
@app.after_request
def add_no_cache_headers(resp: Response) -> Response:
    """Add HTTP headers to disable client‑side caching of API responses.

    Without these headers the dashboard may display stale data after a page
    reload, especially when the underlying JSON has changed.
    """
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp

# ------------------------------------------------------------
# Helper utilities
# ------------------------------------------------------------
def is_dir_accessible(path: Path) -> bool:
    """Return ``True`` if *path* exists, is a directory, and can be listed.

    Permission errors are caught and translated to ``False`` so callers can
    gracefully fall back to alternative locations.
    """
    if not path.exists() or not path.is_dir():
        return False
    try:
        list(path.iterdir())
        return True
    except PermissionError:
        return False

def resolve_company_dir() -> tuple[Path, str]:
    """Select the first accessible company directory.

    Preference order:
    1. ``~/company`` (safe home directory)
    2. ``~/Desktop/company``
    3. ``~/公司根目录`` (legacy Chinese name)

    Returns a tuple ``(Path, source_tag)`` where *source_tag* indicates the
    chosen location or why a fallback was needed.
    """
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

def now_str() -> str:
    """Return the current datetime formatted as ``YYYY‑MM‑DD HH:MM:SS``."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def parse_due_at(raw: str | None) -> str | None:
    """Normalize a raw ``due_at`` string.

    ``None`` or empty input returns ``None``; otherwise whitespace is stripped.
    """
    if not raw:
        return None
    return raw.strip() or None

def get_configured_host() -> str:
    """Read ``CEO_CONSOLE_HOST`` from the environment or fall back to default."""
    return os.environ.get("CEO_CONSOLE_HOST", DEFAULT_HOST).strip() or DEFAULT_HOST

def get_configured_port() -> int:
    """Read ``CEO_CONSOLE_PORT`` from the environment, validate, and return an int.

    Invalid values default to ``DEFAULT_PORT``.
    """
    raw = os.environ.get("CEO_CONSOLE_PORT", str(DEFAULT_PORT)).strip()
    try:
        port = int(raw)
    except ValueError:
        return DEFAULT_PORT
    return port if 1 <= port <= 65535 else DEFAULT_PORT

def get_dispatch_timeout_seconds() -> int:
    """Read the dispatch timeout from environment, ensuring a minimum of 60 s."""
    raw = os.environ.get(
        "CEO_CONSOLE_DISPATCH_TIMEOUT_SECONDS",
        str(DEFAULT_DISPATCH_TIMEOUT_SECONDS),
    ).strip()
    try:
        timeout = int(raw)
    except ValueError:
        return DEFAULT_DISPATCH_TIMEOUT_SECONDS
    return max(60, timeout)

def ensure_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    """Add *column* to *table* if it does not already exist.

    ``ddl`` is the full ``column_name TYPE …`` fragment used in the ``ALTER``
    statement.  This helper enables forward‑compatible schema migrations.
    """
    cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")

def init_db() -> None:
    """Create the ``tasks`` table and ensure all dynamic columns exist.

    This function is idempotent – calling it repeatedly will not duplicate
    tables or columns.
    """
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
        # Ensure all optional execution columns are present.
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
        conn.commit()

def db_conn() -> sqlite3.Connection:
    """Return a SQLite connection with ``row_factory`` set for dict‑like access."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def run_pm_command(args: list[str], input_text: str | None = None) -> subprocess.CompletedProcess:
    """Execute the external *PM* script with *args*.

    ``PM_SCRIPT`` points to ``~/ai-team-template/初始化脚本/pm``.  The function raises
    ``FileNotFoundError`` if the script does not exist.
    """
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

def list_projects() -> list[dict]:
    """Enumerate visible project directories under the selected company root.

    The result contains meta‑information used by the frontend, such as the
    presence of ``CLAUDE.md`` or ``.cursorrules``.
    """
    projects: list[dict] = []
    company_dir, _ = resolve_company_dir()
    if not company_dir.exists():
        return projects
    try:
        entries = sorted(company_dir.iterdir(), key=lambda x: x.name)
    except PermissionError:
        return projects
    for p in entries:
        if not p.is_dir() or p.name.startswith('.'):
            continue
        projects.append(
            {
                "name": p.name,
                "path": str(p),
                "has_ai_rule": (p / "CLAUDE.md").exists(),
                "has_cursorrules": (p / ".cursorrules").exists(),
                "has_coordinator": (p / ".agent-coordinator").exists(),
                "has_execution_checklist": (p / "docs" / "执行清单.md").exists(),
            }
        )
    return projects

def list_archived_projects() -> list[str]:
    """Return a sorted list of archived project names under ``.archive``."""
    company_dir, _ = resolve_company_dir()
    archive_dir = company_dir / ".archive"
    if not archive_dir.exists():
        return []
    try:
        return sorted([p.name for p in archive_dir.iterdir() if p.is_dir()])
    except PermissionError:
        return []

def get_task_counts(conn: sqlite3.Connection) -> dict:
    """Return a mapping of task ``status`` → count for the four core statuses.

    The base dictionary ensures all expected keys are present even when zero.
    """
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
    """Fetch tasks whose ``due_at`` is past and not yet completed."""
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
    """Return tasks whose deadline is within the next *minutes* minutes.

    Used for the "即将到期" UI widget.
    """
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

def row_to_task(row: sqlite3.Row) -> dict[str, Any]:
    """Convert a SQLite row into a plain ``dict`` used by the API layer."""
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
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }

def fetch_tasks(conn: sqlite3.Connection, filters: dict[str, str] | None = None) -> list[sqlite3.Row]:
    """Retrieve tasks that match optional ``filters``.

    Supported filter keys: ``q`` (search across multiple text fields),
    ``project``, ``status``, ``priority``, ``execution_state``.
    """
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
    sql += " ORDER BY created_at DESC"
    return conn.execute(sql, args).fetchall()

def tool_candidates(tool_name: str) -> list[str]:
    """Map a high‑level AI tool name to possible binary candidates.

    The mapping is used by ``resolve_tool_command`` to locate an executable.
    """
    mapping = {
        "Claude Code": ["claude"],
        "Codex": ["codex"],
        "Gemini": ["gemini"],
        "Antigravity": ["openclaw", "antigravity"],
        "Cursor": ["cursor", "cursor-agent"],
    }
    return mapping.get(tool_name, [])

def resolve_tool_command(tool_name: str) -> str | None:
    """Find an executable for *tool_name*.

    Search order:
    1. System ``PATH`` via ``shutil.which``.
    2. Additional directories listed in ``extra_dirs`` (Homebrew, user bin, etc.).
    Returns the absolute path or ``None`` if not found.
    """
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
    """Construct the command line to invoke *tool_name* with *prompt*.

    Returns ``(cmd_list, None)`` on success or ``(None, error_msg)`` when the
    tool cannot be resolved.
    """
    cmd_path = resolve_tool_command(tool_name)
    if not cmd_path:
        return None, f"未找到可执行命令候选：{tool_candidates(tool_name)}"

    if tool_name == "Claude Code":
        return [cmd_path, "-p", "--output-format", "text", prompt], None
    if tool_name == "Gemini":
        return [cmd_path, "-p", prompt], None
    if tool_name == "Antigravity":
        return [cmd_path, "agent", "--local", "--agent", "main", "--message", prompt, "--json"], None
    if tool_name == "Codex":
        return [cmd_path, prompt], None
    if tool_name == "Cursor":
        return None, "Cursor CLI 当前用于打开IDE窗口，不支持稳定的无头自动执行。请改用 Claude/Gemini/Antigravity/Codex。"
    return [cmd_path, prompt], None

def pick_fallback_tool(preferred_tools: list[str] | None = None) -> tuple[str | None, str | None]:
    """Select the first *runnable* tool from ``preferred_tools``.

    ``preferred_tools`` defaults to ``["Claude Code", "Gemini"]``.
    Returns a ``(tool_name, None)`` tuple or ``(None, error_msg)`` if none are
    available.
    """
    ordered = preferred_tools or ["Claude Code", "Gemini"]
    status = get_tools_status_cached()
    for tool in ordered:
        info = status.get(tool) or {}
        if info.get("available") and info.get("runnable"):
            return tool, None
    return None, "未找到可自动调度的后备工具（需要可运行的 Claude Code 或 Gemini）"

def check_command_runnable(path: str) -> tuple[bool, str | None]:
    """Quickly test whether a CLI supports ``--help`` without side effects.

    Returns ``(True, None)`` if the command exits with status 0; otherwise a
    tuple ``(False, error_message)``.
    """
    try:
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

def get_tools_status_cached() -> dict[str, Any]:
    """Cache the availability and runnable status of AI tools for 60 seconds.

    The cache lives in the module‑level ``_TOOL_STATUS_CACHE`` dict.
    """
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
        }
    _TOOL_STATUS_CACHE["ts"] = now
    _TOOL_STATUS_CACHE["data"] = data
    return data

def launchd_service_status() -> dict[str, Any]:
    """Query macOS ``launchctl`` for the ``com.oneperson.ceo-console`` service.

    Returns a dict indicating whether the label is loaded, its PID, exit code
    and any raw output or error.
    """
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
    """Generate a Chinese prompt that describes the task for an AI agent.

    The prompt includes project, title, priority, acceptance criteria, notes,
    and a short instruction for the agent to analyze before acting.
    """
    return (
        f"你是项目执行智能体。请在项目 {task['project']} 中完成任务：{task['title']}。\\n"
        f"优先级：{task['priority']}\\n"
        f"验收标准：{task['acceptance_criteria'] or '未提供'}\\n"
        f"备注：{task['notes'] or '无'}\\n"
        "要求：先分析后实施，完成后给出变更说明和验证结果。"
    )

def set_task_execution_state(task_id: int, state: str, **kwargs: Any) -> None:
    """Update ``execution_state`` and optional auxiliary columns for *task_id*.

    ``state`` is validated against ``ALLOWED_EXEC_STATE``; invalid values are
    coerced to ``failed``.  ``kwargs`` may contain any additional columns such
    as ``execution_error`` or timestamps.
    """
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
    """Append a timestamped *message* to the ``execution_progress`` column.

    The column is capped at 8 000 characters to keep the DB lightweight.
    """
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
    """Return the last *max_chars* characters of *path*.

    The function reads from the end of the file to avoid loading the whole log
    into memory, which is useful for large task output files.
    """
    if not path.exists():
        return ""
    max_bytes = max_chars * 4
    with path.open("rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        f.seek(max(0, size - max_bytes), os.SEEK_SET)
        data = f.read()
    return data.decode("utf-8", errors="replace")[-max_chars:]

# ------------------------------------------------------------
# Task execution – now wrapped as a Celery task (see tasks.py)
# ------------------------------------------------------------
def dispatch_task_worker(task_id: int) -> None:
    """Execute a task by invoking the appropriate AI CLI.

    This function is **intentionally side‑effect heavy**: it updates the SQLite
    DB, writes log files under ``data/run-logs/``, and changes the task's
    ``status`` field.  It is now used as a Celery task (see ``tasks.py``).
    """
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

    # Auto‑fallback if the primary tool cannot be run headlessly.
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
        conn.execute(
            "UPDATE tasks SET status = 'AI执行中', updated_at = ? WHERE id = ?",
            (now_str(), task_id),
        )
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
                conn.execute(
                    "UPDATE tasks SET status = '待人工审查', updated_at = ? WHERE id = ?",
                    (now_str(), task_id),
                )
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

# ------------------------------------------------------------
# Flask routes
# ------------------------------------------------------------
@app.route("/")
def dashboard() -> str:
    """Render the main dashboard page using ``templates/dashboard.html``."""
    return render_template("dashboard.html")

@app.route("/api/projects")
def api_projects():
    """Return JSON describing the available projects and any permission warnings."""
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
    """Create a new project by delegating to the external PM script."""
    data = request.get_json(force=True, silent=False) or {}
    name = str(data.get("name", "")).strip()
    if not name:
        return jsonify({"error": "name is required"}), 400
    result = run_pm_command(["new", name])
    status = 200 if result.returncode == 0 else 400
    return jsonify({"ok": result.returncode == 0, "stdout": result.stdout, "stderr": result.stderr}), status

@app.route("/api/projects/<name>/archive", methods=["POST"])
def api_project_archive(name: str):
    result = run_pm_command(["archive", name])
    status = 200 if result.returncode == 0 else 400
    return jsonify({"ok": result.returncode == 0, "stdout": result.stdout, "stderr": result.stderr}), status

@app.route("/api/projects/<name>/unarchive", methods=["POST"])
def api_project_unarchive(name: str):
    result = run_pm_command(["unarchive", name])
    status = 200 if result.returncode == 0 else 400
    return jsonify({"ok": result.returncode == 0, "stdout": result.stdout, "stderr": result.stderr}), status

@app.route("/api/projects/<name>", methods=["DELETE"])
def api_project_delete(name: str):
    data = request.get_json(force=True, silent=True) or {}
    confirm_name = str(data.get("confirm_name", "")).strip()
    if confirm_name != name:
        return jsonify({"error": "confirm_name must match project name"}), 400
    result = run_pm_command(["delete", name], input_text=name + "\n")
    status = 200 if result.returncode == 0 else 400
    return jsonify({"ok": result.returncode == 0, "stdout": result.stdout, "stderr": result.stderr}), status

@app.route("/api/tools/status")
def api_tools_status():
    return jsonify(get_tools_status_cached())

@app.route("/api/tasks", methods=["GET"])
def api_tasks():
    init_db()
    filters = {
        "q": request.args.get("q", ""),
        "project": request.args.get("project", ""),
        "status": request.args.get("status", ""),
        "priority": request.args.get("priority", ""),
        "execution_state": request.args.get("execution_state", ""),
    }
    with closing(db_conn()) as conn:
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
    }
    with closing(db_conn()) as conn:
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
                value = "\"" + value.replace("\"", "\\\"") + "\""
            line.append(value)
        chunks.append(",".join(line) + "\n")
    content = "".join(clunks)
    return Response(
        content,
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="tasks.csv"'},
    )

@app.route("/api/tasks", methods=["POST"])
def api_create_task():
    """Insert a new task into the DB and enqueue it for asynchronous execution.

    The route returns the created ``task_id``.  The heavy lifting is performed by
    the Celery worker defined in ``tasks.py``.
    """
    init_db()
    data = request.get_json(force=True, silent=False) or {}
    title = str(data.get("title", "")).strip()
    project = str(data.get("project", "")).strip()
    assignee_ai = str(data.get("assignee_ai", "Other")).strip()
    status = str(data.get("status", "待分配")).strip()
    priority = str(data.get("priority", "P1")).strip()
    due_at = parse_due_at(data.get("due_at"))
    estimated_finish_at = parse_due_at(data.get("estimated_finish_at"))
    acceptance_criteria = str(data.get("acceptance_criteria", "")).strip()
    notes = str(data.get("notes", "")).strip()

    if not title:
        return jsonify({"error": "title is required"}), 400

    with closing(db_conn()) as conn:
        cur = conn.execute(
            """
            INSERT INTO tasks (title, project, assignee_ai, status, priority, due_at, acceptance_criteria, notes, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?)
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
                now_str(),
                now_str(),
            ),
        )
        task_id = cur.lastrowid
        conn.commit()

    # Enqueue Celery task (non‑blocking)
    try:
        from .tasks import dispatch_task_worker
        dispatch_task_worker.delay(task_id)
    except Exception:
        # Fallback: run synchronously if Celery is not available (useful for dev).
        dispatch_task_worker(task_id)

    return jsonify({"ok": True, "task_id": task_id}), 201

if __name__ == "__main__":
    # Development mode – run Flask directly.
    init_db()
    app.run(host=get_configured_host(), port=get_configured_port(), debug=True)
