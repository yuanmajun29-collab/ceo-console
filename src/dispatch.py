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
from .tools import build_tool_run_command, pick_fallback_tool

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
