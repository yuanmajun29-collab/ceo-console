from __future__ import annotations

import json
import re
import subprocess
import time
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .config import resolve_company_dir
from .db import db_conn, init_db
from .finance import compute_overview as finance_compute_overview
from .projects import find_project_repositories, list_projects
from .tasks import (
    fetch_tasks,
    get_due_soon_tasks,
    get_overdue_tasks,
    get_task_counts,
    reconcile_task_statuses,
    row_to_task,
)


HERMES_MEMORY_FILES = [
    Path.home() / ".hermes" / "memories" / "MEMORY.md",
    Path.home() / ".hermes" / "memories" / "USER.md",
    Path.home()
    / ".hermes"
    / "skills"
    / "productivity"
    / "obsidian-shared-knowledge"
    / "references"
    / "hermes-memory-snapshot.md",
]
_GEMINI_AVAILABLE_CACHE: bool | None = None


def _read_text(path: Path, limit: int = 6000) -> str:
    try:
        if path.exists() and path.is_file():
            return path.read_text(encoding="utf-8", errors="replace")[-limit:]
    except OSError:
        pass
    return ""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        if path.exists() and path.is_file():
            parsed = json.loads(path.read_text(encoding="utf-8"))
            return parsed if isinstance(parsed, dict) else {}
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def _memory_signal() -> dict[str, Any]:
    fragments = []
    files = []
    for path in HERMES_MEMORY_FILES:
        text = _read_text(path, limit=3000)
        if not text:
            continue
        files.append(
            {
                "path": str(path),
                "mtime": datetime.fromtimestamp(path.stat().st_mtime).isoformat(),
                "chars": len(text),
            }
        )
        fragments.append(text)
    merged = "\n\n".join(fragments)
    keywords = ["todo", "待办", "决策", "decision", "风险", "risk", "follow up", "下一步"]
    highlights = [
        line.strip()
        for line in merged.splitlines()
        if line.strip() and any(k.lower() in line.lower() for k in keywords)
    ][:8]
    return {"files": files, "highlights": highlights, "available": bool(files)}


def _coordinator_signal() -> dict[str, Any]:
    state_path = Path.home() / "company" / ".agent-coordinator" / "state.json"
    raw = _read_json(state_path)
    state = raw.get("state", raw) if isinstance(raw, dict) else {}
    rows = []
    if isinstance(state, dict):
        for key, value in state.items():
            if isinstance(value, dict):
                rows.append(
                    {
                        "key": key,
                        "value": value.get("value", value.get("current", value.get("new_value", value))),
                        "tool": value.get("tool") or value.get("set_by") or value.get("source") or "",
                        "reason": value.get("reason") or "",
                        "time": value.get("time") or value.get("updated_at") or value.get("timestamp") or "",
                    }
                )
            else:
                rows.append({"key": key, "value": value, "tool": "", "reason": "", "time": ""})
    return {
        "path": str(state_path),
        "available": state_path.exists(),
        "state": state if isinstance(state, dict) else {},
        "recent": rows[-10:],
    }


def _git_log(repo_path: Path) -> list[dict[str, str]]:
    try:
        proc = subprocess.run(
            ["git", "log", "--since=7 days ago", "--pretty=format:%h%x09%cr%x09%s", "-n", "5"],
            cwd=str(repo_path),
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=4,
        )
    except Exception:
        return []
    if proc.returncode != 0:
        return []
    commits = []
    for line in proc.stdout.splitlines():
        parts = line.split("\t", 2)
        if len(parts) == 3:
            commits.append({"hash": parts[0], "relative_time": parts[1], "subject": parts[2]})
    return commits


def _project_delivery_signal() -> list[dict[str, Any]]:
    projects = list_projects()
    items: list[dict[str, Any]] = []
    now = datetime.now()
    for project in projects:
        repos = find_project_repositories(project)
        project_commits: list[dict[str, str]] = []
        last_active_at: datetime | None = None
        for repo in repos[:4]:
            repo_path = Path(repo["path"])
            project_commits.extend(_git_log(repo_path))
            try:
                mtime = datetime.fromtimestamp(repo_path.stat().st_mtime)
                last_active_at = max(last_active_at, mtime) if last_active_at else mtime
            except OSError:
                pass
        inactive_days = (now - last_active_at).days if last_active_at else None
        items.append(
            {
                "name": project["name"],
                "path": project["path"],
                "governance_score": project.get("governance_score", 0),
                "repos": len(repos),
                "recent_commits": project_commits[:8],
                "inactive_days": inactive_days,
                "risk": inactive_days is not None and inactive_days >= 3,
            }
        )
    return items


def _task_signal() -> dict[str, Any]:
    init_db()
    with closing(db_conn()) as conn:
        reconcile_task_statuses(conn)
        conn.commit()
        counts = get_task_counts(conn)
        overdue = [row_to_task(r) for r in get_overdue_tasks(conn)]
        due_soon = [row_to_task(r) for r in get_due_soon_tasks(conn, minutes=24 * 60)]
        failed = [
            row_to_task(r)
            for r in conn.execute(
                """
                SELECT *
                FROM tasks
                WHERE execution_state IN ('failed', 'unsupported')
                ORDER BY updated_at DESC
                LIMIT 8
                """
            ).fetchall()
        ]
        review = [
            row_to_task(r)
            for r in fetch_tasks(conn, {"status": "待人工审查", "order_by": "priority"})[:8]
        ]
    return {"counts": counts, "overdue": overdue, "due_soon": due_soon, "failed": failed, "review": review}


def _finance_signal() -> dict[str, Any]:
    try:
        overview = finance_compute_overview()
    except Exception as exc:
        return {"available": False, "error": str(exc)}
    return {
        "available": True,
        "currency": overview.get("currency", "CNY"),
        "current_month_income": overview.get("labels", {}).get("current_month_income", "-"),
        "current_month_expense": overview.get("labels", {}).get("current_month_expense", "-"),
        "current_month_net": overview.get("labels", {}).get("current_month_net", "-"),
        "subscription_monthly": overview.get("labels", {}).get("subscription_monthly", "-"),
        "runway": overview.get("labels", {}).get("runway", "-"),
        "subscription_count": overview.get("subscription_count", 0),
    }


def _parse_llm_priority_output(output: str) -> list[dict[str, Any]]:
    suggestions: list[dict[str, Any]] = []
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        match = re.match(r"^(P[0-2]|[高中特低])\s*[:：]\s*(.+)$", line, flags=re.I)
        if not match:
            continue
        label, body = match.groups()
        parts = [part.strip() for part in re.split(r"\s*\|\s*", body) if part.strip()]
        if not parts:
            continue
        title = parts[0]
        reason = parts[1] if len(parts) > 1 else "LLM 基于当前项目、风险和任务状态排序。"
        tool = parts[2] if len(parts) > 2 else "AI Commander"
        normalized_priority = {"P0": "高", "P1": "高", "P2": "中"}.get(label.upper(), label)
        intent = f"{title}（推荐工具：{tool}）"
        suggestions.append(
            {
                "priority": normalized_priority,
                "title": title,
                "reason": reason,
                "intent": intent,
                "source": "gemini",
                "recommended_tool": tool,
                "action": {"type": "commander", "intent": intent},
            }
        )
        if len(suggestions) >= 3:
            break
    return suggestions


def _llm_priority_suggestions(
    tasks: dict[str, Any], projects: list[dict[str, Any]], risks: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    # 先检查 gemini 是否可用，不可用直接返回
    if not _gemini_available():
        return []

    prompt = f"""你是 CEO 的战略顾问。请分析以下公司的今日状态，选出最重要的 3 件事。

项目状态：{json.dumps(projects[:12], ensure_ascii=False)}
风险：{json.dumps(risks, ensure_ascii=False)}
待办任务：{json.dumps({k: tasks.get(k, []) for k in ["overdue", "due_soon", "failed", "review"]}, ensure_ascii=False)}

请按优先级输出 3 条建议，每条一行，格式严格为：
P1: [建议行动] | [原因] | [推荐工具]
"""
    try:
        result = subprocess.run(
            ["gemini", "-p", prompt],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
    except Exception:
        return []
    if result.returncode != 0:
        return []
    return _parse_llm_priority_output(result.stdout or "")


def _gemini_available() -> bool:
    global _GEMINI_AVAILABLE_CACHE
    if _GEMINI_AVAILABLE_CACHE is not None:
        return _GEMINI_AVAILABLE_CACHE
    try:
        r = subprocess.run(["gemini", "--version"], capture_output=True, timeout=3)
        _GEMINI_AVAILABLE_CACHE = r.returncode == 0
    except Exception:
        _GEMINI_AVAILABLE_CACHE = False
    return _GEMINI_AVAILABLE_CACHE


def _rule_based_priority_suggestions(
    tasks: dict[str, Any], projects: list[dict[str, Any]], finance: dict[str, Any], memory: dict[str, Any]
) -> list[dict[str, Any]]:
    suggestions: list[dict[str, Any]] = []
    for task in tasks["review"][:3]:
        suggestions.append(
            {
                "priority": "高",
                "title": f"审查 {task['project']}：{task['title']}",
                "reason": "任务已由 AI 执行完成，等待 CEO 验收。",
                "intent": f"审查任务 #{task['id']} 的执行结果并给出通过或驳回建议",
                "action": {"type": "open_task", "task_id": task["id"]},
            }
        )
    for task in tasks["overdue"][:3]:
        suggestions.append(
            {
                "priority": "高",
                "title": f"处理超期任务：{task['title']}",
                "reason": f"{task['project']} 任务已超过截止时间。",
                "intent": f"重新评估并推进超期任务：{task['title']}",
                "action": {"type": "commander", "intent": f"重新评估并推进超期任务：{task['title']}"},
            }
        )
    for project in projects:
        if project.get("risk"):
            suggestions.append(
                {
                    "priority": "中",
                    "title": f"关注 {project['name']} 本周迭代",
                    "reason": f"项目约 {project.get('inactive_days')} 天无明显活跃。",
                    "intent": f"扫描 {project['name']} 的阻塞并制定本周推进计划",
                    "action": {"type": "commander", "intent": f"扫描 {project['name']} 的阻塞并制定本周推进计划"},
                }
            )
    if finance.get("available") and finance.get("subscription_count", 0):
        suggestions.append(
            {
                "priority": "低",
                "title": "复核本月订阅支出",
                "reason": f"当前月度订阅合计 {finance.get('subscription_monthly')}。",
                "intent": "复核本月订阅支出，找出可暂停或清理的服务",
                "action": {"type": "commander", "intent": "复核本月订阅支出，找出可暂停或清理的服务"},
            }
        )
    if memory.get("highlights") and not suggestions:
        suggestions.append(
            {
                "priority": "中",
                "title": "整理 Hermes 记忆中的待办",
                "reason": "最近记忆里出现待办、决策或风险信号。",
                "intent": "整理 Hermes 记忆中的待办、决策和风险，生成今日执行队列",
                "action": {"type": "commander", "intent": "整理 Hermes 记忆中的待办、决策和风险，生成今日执行队列"},
            }
        )
    return suggestions[:8]


def _priority_suggestions(
    tasks: dict[str, Any],
    projects: list[dict[str, Any]],
    finance: dict[str, Any],
    memory: dict[str, Any],
    risks: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    llm_suggestions = _llm_priority_suggestions(tasks, projects, risks or [])
    if llm_suggestions:
        return llm_suggestions
    return _rule_based_priority_suggestions(tasks, projects, finance, memory)


_BRIEF_CACHE: dict[str, Any] = {"ts": 0, "data": None}
_BRIEF_CACHE_TTL = 120  # 缓存 2 分钟


def generate_daily_brief() -> dict[str, Any]:
    now = time.time()
    if now - _BRIEF_CACHE.get("ts", 0) < _BRIEF_CACHE_TTL and _BRIEF_CACHE.get("data"):
        return _BRIEF_CACHE["data"]

    memory = _memory_signal()
    coordinator = _coordinator_signal()
    projects = _project_delivery_signal()
    tasks = _task_signal()
    finance = _finance_signal()
    company_dir, company_source = resolve_company_dir()

    risks = []
    if tasks["overdue"]:
        risks.append({"level": "high", "message": f"{len(tasks['overdue'])} 个任务已超期"})
    if tasks["failed"]:
        risks.append({"level": "high", "message": f"{len(tasks['failed'])} 个自动调度失败或不支持"})
    inactive_projects = [p for p in projects if p.get("risk")]
    if inactive_projects:
        risks.append({"level": "medium", "message": f"{len(inactive_projects)} 个项目 3 天以上无活跃"})
    if not coordinator["available"]:
        risks.append({"level": "medium", "message": "Coordinator state.json 不可用，跨工具状态可能未同步"})

    suggestions = _priority_suggestions(tasks, projects, finance, memory, risks)
    return {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "company_dir": str(company_dir),
        "company_source": company_source,
        "sections": {
            "project_delivery": {
                "summary": f"{len(projects)} 个活跃项目，{len(inactive_projects)} 个需要关注",
                "items": projects,
            },
            "customers": {"summary": "无新消息", "items": []},
            "finance": finance,
            "growth": {"summary": "上周内容发布数据未接入，建议启动内容巡航", "items": []},
        },
        "tasks": tasks,
        "memory": memory,
        "coordinator": coordinator,
        "risks": risks,
        "suggestions": suggestions,
        "one_click_actions": [s["action"] for s in suggestions if s.get("action")],
    }
    _BRIEF_CACHE["ts"] = now
    _BRIEF_CACHE["data"] = brief
    return brief
