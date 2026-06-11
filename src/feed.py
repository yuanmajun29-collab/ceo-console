from __future__ import annotations

import json
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import DB_PATH, now_str
from .db import db_conn, init_db
from .risk_monitor import get_all_risks
from .subscription_reminders import get_due_reminders
from .tasks import fetch_tasks, get_task_counts, reconcile_task_statuses, row_to_task

HERMES_MEMORY_PATH = Path.home() / ".hermes" / "memories" / "MEMORY.md"
COORDINATOR_STATE_PATH = Path.home() / "company" / ".agent-coordinator" / "state.json"
MONITORED_REPOS = {
    "ccec-timer-system": Path.home() / "company" / "ccec-timer-system",
    "edge-caculate-box": Path.home() / "company" / "edge-caculate-box",
}

PRIORITY_SCORE = {"P0": 0, "high": 0, "P1": 1, "warning": 1, "medium": 1, "P2": 2, "low": 2}


def _iso_now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _parse_dt(value: str | None) -> datetime:
    if not value:
        return datetime.min
    text = value.replace("Z", "+00:00")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            pass
    try:
        parsed = datetime.fromisoformat(text)
        return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed
    except ValueError:
        return datetime.min


def _priority_rank(priority: str) -> int:
    return PRIORITY_SCORE.get(priority, 9)


def _timestamp_rank(value: str | None) -> float:
    parsed = _parse_dt(value)
    if parsed == datetime.min:
        return 0.0
    return parsed.timestamp()


def _action(action_id: str, label: str, kind: str, intent: str | None = None) -> dict[str, Any]:
    return {"id": action_id, "label": label, "kind": kind, "intent": intent}


def _feed_item(
    *,
    item_id: str,
    item_type: str,
    priority: str,
    summary: str,
    details: str,
    timestamp: str | None,
    source: str,
    ai_action: str,
    ai_reason: str,
    actions: list[dict[str, Any]] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": item_id,
        "type": item_type,
        "priority": priority,
        "summary": summary,
        "details": details,
        "timestamp": timestamp or _iso_now(),
        "source": source,
        "ai_suggestion": {
            "action": ai_action,
            "tool": "Codex",
            "reason": ai_reason,
            "one_click": f"/api/commander/execute?intent={ai_action}",
        },
        "actions": actions
        or [
            _action("execute", "执行", "execute", ai_action),
            _action("ignore", "忽略", "ignore"),
            _action("snooze", "推迟", "snooze"),
        ],
        "metadata": metadata or {},
    }


def _read_hermes_memory() -> list[dict[str, Any]]:
    if not HERMES_MEMORY_PATH.exists():
        return []
    try:
        text = HERMES_MEMORY_PATH.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    chunks = [part.strip() for part in text.split("§") if part.strip()]
    items: list[dict[str, Any]] = []
    for idx, chunk in enumerate(chunks[-5:], start=1):
        first_line = next((line.strip() for line in chunk.splitlines() if line.strip()), "")
        if not first_line:
            continue
        summary = first_line[:120]
        items.append(
            _feed_item(
                item_id=f"memory-{idx}",
                item_type="memory",
                priority="P2",
                summary=f"Hermes 记忆：{summary}",
                details=chunk[:1200],
                timestamp=None,
                source="Hermes memory",
                ai_action=f"基于 Hermes 记忆检查：{summary}",
                ai_reason="长期记忆出现新的项目约定或跨工具状态，适合纳入今日判断。",
                metadata={"path": str(HERMES_MEMORY_PATH)},
            )
        )
    return items


def _read_coordinator_state() -> list[dict[str, Any]]:
    if not COORDINATOR_STATE_PATH.exists():
        return []
    try:
        payload = json.loads(COORDINATOR_STATE_PATH.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return []

    state = payload.get("state") if isinstance(payload, dict) else {}
    if not isinstance(state, dict):
        return []

    rows = []
    for key, value in state.items():
        if isinstance(value, dict):
            rows.append((key, value))
    rows.sort(key=lambda pair: str(pair[1].get("timestamp") or ""), reverse=True)

    items: list[dict[str, Any]] = []
    for key, entry in rows[:6]:
        value = entry.get("value", "-")
        reason = entry.get("reason") or "未记录原因。"
        tool = entry.get("tool") or entry.get("set_by") or "unknown"
        timestamp = entry.get("timestamp")
        items.append(
            _feed_item(
                item_id=f"coordinator-{key}",
                item_type="coordinator",
                priority="P2",
                summary=f"{key} = {value}",
                details=f"来源：{tool}\n原因：{reason}",
                timestamp=str(timestamp) if timestamp else None,
                source="coordinator state",
                ai_action=f"复核共享状态 {key}",
                ai_reason="跨工具共享状态发生变化，可能影响当前执行路径。",
                metadata={"key": key, "value": value, "tool": tool},
            )
        )
    return items


def _read_task_feed() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    init_db()
    with closing(db_conn()) as conn:
        reconcile_task_statuses(conn)
        conn.commit()
        rows = fetch_tasks(conn, {"order_by": "updated_at"})[:20]
        counts = get_task_counts(conn)
        review_count = conn.execute("SELECT COUNT(*) FROM tasks WHERE status = '待人工审查'").fetchone()[0]
    items: list[dict[str, Any]] = []
    for row in rows:
        task = row_to_task(row)
        status = task.get("status") or "待分配"
        priority = task.get("priority") or "P2"
        title = task.get("title") or f"任务 #{task.get('id')}"
        project = task.get("project") or "-"
        details = "\n".join(
            part
            for part in [
                f"项目：{project}",
                f"状态：{status} / {task.get('execution_state')}",
                f"负责人：{task.get('assignee_ai')}",
                f"到期：{task.get('due_at') or '-'}",
                f"验收标准：{task.get('acceptance_criteria') or '-'}",
                f"备注：{task.get('notes') or '-'}",
            ]
            if part
        )
        if status == "待人工审查":
            ai_action = f"审查任务 #{task['id']}：{title}"
            reason = "任务已由 AI 执行完成，当前需要 CEO 验收或驳回。"
        elif task.get("execution_state") in {"failed", "unsupported"}:
            ai_action = f"重试或改写任务 #{task['id']}：{title}"
            reason = "自动执行失败，优先清理以恢复任务队列。"
            priority = "P0"
        else:
            ai_action = f"推进任务 #{task['id']}：{title}"
            reason = "任务仍在队列中，可按优先级继续派发。"
        items.append(
            _feed_item(
                item_id=f"task-{task['id']}",
                item_type="task",
                priority=priority,
                summary=f"{project} · {title}",
                details=details,
                timestamp=task.get("updated_at") or task.get("created_at"),
                source="tasks DB",
                ai_action=ai_action,
                ai_reason=reason,
                actions=[
                    _action("execute", "开始执行", "execute", ai_action),
                    _action("ignore", "忽略", "ignore"),
                    _action("snooze", "推迟", "snooze"),
                ],
                metadata={"task_id": task["id"], "status": status, "project": project},
            )
        )
    return items, {"counts": counts, "review": review_count}


def _git_log_for_repo(name: str, path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(path),
                "log",
                "-5",
                "--date=iso",
                "--pretty=format:%H%x1f%h%x1f%ad%x1f%s",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=4,
        )
    except Exception as exc:
        return [
            _feed_item(
                item_id=f"git-error-{name}",
                item_type="git",
                priority="P1",
                summary=f"{name} Git 日志读取失败",
                details=str(exc),
                timestamp=None,
                source="project git logs",
                ai_action=f"检查 {name} 仓库状态",
                ai_reason="仓库日志不可读，可能影响项目活跃度判断。",
            )
        ]
    if result.returncode != 0:
        return [
            _feed_item(
                item_id=f"git-error-{name}",
                item_type="git",
                priority="P1",
                summary=f"{name} 暂无可用 Git 提交",
                details=(result.stderr or "git log 未返回提交。")[:800],
                timestamp=None,
                source="project git logs",
                ai_action=f"初始化或检查 {name} 仓库提交历史",
                ai_reason="项目没有可读提交历史，无法判断最近进展。",
                metadata={"path": str(path), "returncode": result.returncode},
            )
        ]

    items: list[dict[str, Any]] = []
    for line in result.stdout.splitlines():
        parts = line.split("\x1f")
        if len(parts) != 4:
            continue
        full_hash, short_hash, committed_at, subject = parts
        items.append(
            _feed_item(
                item_id=f"git-{name}-{short_hash}",
                item_type="git",
                priority="P2",
                summary=f"{name} 提交 {short_hash}: {subject}",
                details=f"仓库：{path}\n提交：{full_hash}\n时间：{committed_at}\n摘要：{subject}",
                timestamp=committed_at,
                source="project git logs",
                ai_action=f"审查 {name} 最新提交 {short_hash}",
                ai_reason="项目提交是实时进展信号，可用于判断是否需要验收、测试或合并。",
                metadata={"project": name, "path": str(path), "commit": full_hash},
            )
        )
    return items


def _read_git_feed() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for name, path in MONITORED_REPOS.items():
        items.extend(_git_log_for_repo(name, path))
    return items


def _read_risk_feed() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for idx, risk in enumerate(get_all_risks(), start=1):
        priority = "P0" if risk.get("level") == "high" else "P1"
        message = str(risk.get("message") or risk.get("title") or risk.get("type") or "风险预警")
        details = "\n".join(f"{key}: {value}" for key, value in risk.items() if value is not None)
        timestamp = risk.get("last_commit_at") or risk.get("due_at")
        items.append(
            _feed_item(
                item_id=f"risk-{risk.get('type', 'risk')}-{risk.get('task_id') or risk.get('project') or idx}",
                item_type="risk",
                priority=priority,
                summary=message,
                details=details,
                timestamp=str(timestamp) if timestamp else None,
                source="risk_monitor",
                ai_action=f"处理风险：{message}",
                ai_reason="风险监控已标记该事项，适合进入今日焦点。",
                actions=[
                    _action("execute", "处理风险", "execute", f"处理风险：{message}"),
                    _action("ignore", "忽略", "ignore"),
                    _action("snooze", "推迟", "snooze"),
                ],
                metadata=risk,
            )
        )
    return items


def _read_subscription_due_feed() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for reminder in get_due_reminders(7):
        priority = "P0" if reminder["status"] in {"expired", "due_today"} else "P1"
        summary = f"续费提醒：{reminder['tool_name']} {reminder['status_label']}"
        details = "\n".join(
            part
            for part in [
                f"工具：{reminder['tool_name']}",
                f"服务商：{reminder['provider']}",
                f"套餐：{reminder.get('plan_name') or '-'}",
                f"续费日期：{reminder.get('renewal_date') or '-'}",
                f"续费链接：{reminder.get('renewal_url') or '-'}",
                f"备注：{reminder.get('notes') or '-'}",
            ]
            if part
        )
        items.append(
            _feed_item(
                item_id=f"subscription-due-{reminder['id']}",
                item_type="subscription_due",
                priority=priority,
                summary=summary,
                details=details,
                timestamp=reminder.get("renewal_date"),
                source="subscription_reminders",
                ai_action=f"处理 {reminder['tool_name']} 续费",
                ai_reason="订阅续费窗口已开启，避免额度中断影响 AI 工具链。",
                actions=[
                    _action("open", "打开续费链接", "link", reminder.get("renewal_url")),
                    _action("ignore", "忽略", "ignore"),
                    _action("snooze", "推迟", "snooze"),
                ],
                metadata=reminder,
            )
        )
    return items


def _read_feed_sources() -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    metrics: dict[str, Any] = {"tasks": 0, "review": 0}
    source_status: dict[str, Any] = {}
    all_items: list[dict[str, Any]] = []

    jobs = {
        "hermes_memory": _read_hermes_memory,
        "coordinator_state": _read_coordinator_state,
        "tasks_db": _read_task_feed,
        "project_git_logs": _read_git_feed,
        "risk_monitor": _read_risk_feed,
        "subscription_reminders": _read_subscription_due_feed,
    }
    with ThreadPoolExecutor(max_workers=len(jobs)) as executor:
        futures = {executor.submit(fn): name for name, fn in jobs.items()}
        for future in as_completed(futures):
            name = futures[future]
            try:
                result = future.result()
            except Exception as exc:
                source_status[name] = {"ok": False, "error": str(exc)}
                continue
            source_status[name] = {"ok": True}
            if name == "tasks_db":
                task_items, task_metrics = result
                all_items.extend(task_items)
                counts = task_metrics.get("counts") or {}
                metrics["tasks"] = sum(int(value or 0) for value in counts.values())
                metrics["review"] = int(task_metrics.get("review") or 0)
            else:
                all_items.extend(result)

    return all_items, metrics, source_status


def build_feed() -> dict[str, Any]:
    items, metrics, sources = _read_feed_sources()
    items.sort(key=lambda item: (_timestamp_rank(item.get("timestamp")), _priority_rank(item.get("priority", ""))), reverse=True)
    focus_candidates = sorted(
        items,
        key=lambda item: (_priority_rank(item.get("priority", "")), -_timestamp_rank(item.get("timestamp"))),
    )
    risks = [item for item in items if item.get("type") == "risk"]
    projects = {item.get("metadata", {}).get("project") for item in items if item.get("metadata", {}).get("project")}
    for name, path in MONITORED_REPOS.items():
        if path.exists():
            projects.add(name)

    return {
        "generated_at": _iso_now(),
        "items": items,
        "today_focus": focus_candidates[:3],
        "metrics": {
            "projects": len(projects),
            "tasks": metrics.get("tasks", 0),
            "risks": len(risks),
            "review": metrics.get("review", 0),
            "unread": 0,
        },
        "sources": sources,
        "db_path": str(DB_PATH),
        "generated_label": now_str(),
    }
