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
from .tools import build_tool_run_command, dispatch_candidate_plan, pick_fallback_tool

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


def execution_tool_label(requested_tool: str, actual_tool: str) -> str:
    return f"{requested_tool}->{actual_tool}" if requested_tool != actual_tool else actual_tool


def run_dispatch_attempt(
    task_id: int,
    row: sqlite3.Row,
    requested_tool: str,
    actual_tool: str,
    cmd: list[str],
    attempt_index: int,
) -> dict[str, Any]:
    set_task_execution_state(
        task_id,
        "running",
        execution_tool=execution_tool_label(requested_tool, actual_tool),
        execution_command=" ".join(cmd),
        execution_started_at=now_str(),
        execution_error=None,
        execution_output=None,
    )
    append_task_progress(task_id, f"开始执行节点 {actual_tool}（第 {attempt_index} 次尝试）：{' '.join(cmd)}")
    with closing(db_conn()) as conn:
        conn.execute("UPDATE tasks SET status = 'AI执行中', updated_at = ? WHERE id = ?", (now_str(), task_id))
        conn.commit()

    company_dir, _ = resolve_company_dir()
    project_dir = company_dir / row["project"]
    logs_dir = DATA_DIR / "run-logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    safe_tool = re.sub(r"[^A-Za-z0-9._-]+", "-", actual_tool).strip("-") or "tool"
    log_path = logs_dir / f"task-{task_id}-{datetime.now().strftime('%Y%m%d-%H%M%S')}-attempt{attempt_index}-{safe_tool}.log"
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
            error = f"{actual_tool} 执行超时（{get_dispatch_timeout_seconds()}秒），日志文件：{log_path}"
            append_task_progress(task_id, error)
            return {"ok": False, "tool": actual_tool, "output": final_output, "error": error, "log_path": str(log_path)}

        if return_code == 0:
            append_task_progress(task_id, f"节点 {actual_tool} 执行完成：成功")
            return {"ok": True, "tool": actual_tool, "output": final_output, "error": None, "log_path": str(log_path)}

        error = f"{actual_tool} 命令退出码 {return_code}，日志文件：{log_path}"
        append_task_progress(task_id, f"节点执行失败：{error}")
        return {"ok": False, "tool": actual_tool, "output": final_output, "error": error, "log_path": str(log_path)}
    except Exception as exc:
        error = f"{actual_tool} 执行异常：{exc}"
        append_task_progress(task_id, error)
        return {"ok": False, "tool": actual_tool, "output": "", "error": error, "log_path": str(log_path)}


def dispatch_task_worker(task_id: int) -> None:
    init_db()
    with closing(db_conn()) as conn:
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if row is None:
        return

    requested_tool = row["assignee_ai"]
    prompt = build_dispatch_prompt(row)
    append_task_progress(task_id, f"任务进入调度队列，请求工具：{requested_tool}")

    try:
        plan = dispatch_candidate_plan(row)
        candidates = plan.get("candidates") or []
        skipped = plan.get("skipped") or []
    except Exception as exc:
        append_task_progress(task_id, f"读取可执行链路失败：{exc}")
        fallback_tool, fallback_err = pick_fallback_tool()
        candidates = [fallback_tool] if fallback_tool else [requested_tool]
        skipped = [] if fallback_tool else [{"tool": requested_tool, "reason": fallback_err or str(exc)}]

    for item in skipped:
        append_task_progress(task_id, f"跳过不可用节点：{item.get('tool')}，原因：{item.get('reason')}")

    initial_failures: list[str] = []
    if not candidates:
        fallback_tool, fallback_err = pick_fallback_tool()
        if fallback_tool:
            candidates = [fallback_tool]
            append_task_progress(task_id, f"可执行链路为空，自动启用全局后备：{fallback_tool}")
        else:
            candidates = [requested_tool]
            initial_failures.append(f"全局后备：{fallback_err}")
            append_task_progress(task_id, f"没有预检可执行 Agent，保底尝试请求工具 {requested_tool}：{fallback_err}")

    append_task_progress(task_id, f"可执行候选链路：{' → '.join(candidates)}")
    failures: list[str] = initial_failures[:]
    last_output = ""
    attempted: list[str] = []

    for index, tool in enumerate(candidates, start=1):
        cmd, build_err = build_tool_run_command(tool, prompt)
        if build_err:
            failures.append(f"{tool}：{build_err}")
            append_task_progress(task_id, f"节点 {tool} 构建执行命令失败，准备故障转移：{build_err}")
            continue

        if requested_tool != tool:
            append_task_progress(task_id, f"故障转移执行：请求工具 {requested_tool}，当前使用 {tool}")
        attempted.append(tool)
        result = run_dispatch_attempt(task_id, row, requested_tool, tool, cmd, index)
        last_output = result.get("output") or last_output
        if result.get("ok"):
            set_task_execution_state(
                task_id,
                "succeeded",
                execution_tool=execution_tool_label(requested_tool, tool),
                execution_output=last_output,
                execution_error=None,
                execution_finished_at=now_str(),
            )
            with closing(db_conn()) as conn:
                conn.execute("UPDATE tasks SET status = '待人工审查', updated_at = ? WHERE id = ?", (now_str(), task_id))
                conn.commit()
            return

        failures.append(f"{tool}：{result.get('error') or '执行失败'}")
        remaining = candidates[index:]
        if remaining:
            append_task_progress(task_id, f"节点 {tool} 失败，故障转移到下一个候选：{remaining[0]}")

    state = "failed" if attempted else "unsupported"
    error = "；".join(failures)[-4000:] if failures else "所有候选节点均不可调度"
    append_task_progress(task_id, f"所有候选节点执行失败：{error}")
    set_task_execution_state(
        task_id,
        state,
        execution_tool=execution_tool_label(requested_tool, attempted[-1]) if attempted else requested_tool,
        execution_output=last_output or None,
        execution_error=error,
        execution_finished_at=now_str(),
    )
