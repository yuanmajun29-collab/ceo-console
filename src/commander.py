from __future__ import annotations

import re
import threading
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import (
    TASK_TYPE_TOOL_ROUTE,
    is_allowed_ai_name,
    normalize_task_type,
    now_str,
)
from .db import db_conn, init_db
from .dispatch import append_task_progress, dispatch_task_worker
from .projects import list_projects
from .tasks import fetch_tasks, reconcile_task_statuses, row_to_task
from .tools import format_route_plan_reason, token_optimized_pipeline


ROUTING_TABLE_PATH = (
    Path.home()
    / ".hermes"
    / "skills"
    / "productivity"
    / "obsidian-shared-knowledge"
    / "references"
    / "cross-tool-routing.md"
)

INTENT_RULES: list[dict[str, Any]] = [
    {
        "task_type": "architecture",
        "tool": "Claude Code",
        "patterns": ["重构", "架构", "大库", "模块设计", "技术方案", "复杂代码库", "review", "审查"],
        "reason": "复杂代码库理解、架构权衡和重构任务推荐 Claude Code。",
    },
    {
        "task_type": "code_edit",
        "tool": "Cursor",
        "patterns": ["日常编码", "ide", "人工精修", "手动改", "cursor"],
        "reason": "日常编码和 IDE 人工接管任务推荐 Cursor。",
    },
    {
        "task_type": "fullstack",
        "tool": "Codex",
        "patterns": ["ceo console", "ceo-console", "app 开发", "flask", "vue", "前端", "后端", "接口", "页面"],
        "reason": "CEO Console 应用开发和可直接落地的前后端改动推荐 Codex。",
    },
    {
        "task_type": "delivery",
        "tool": "PilotDeck",
        "patterns": ["定时", "cron", "后台", "守护", "自动任务", "调度"],
        "reason": "后台定时任务和常驻自动化推荐 PilotDeck。",
    },
    {
        "task_type": "docs",
        "tool": "Antigravity",
        "patterns": ["openclaw", "人格", "角色", "soul", "agent 人格"],
        "reason": "人格化角色和 OpenClaw/SOUL agent 任务推荐 OpenClaw/Antigravity。",
    },
    {
        "task_type": "market_research",
        "tool": "Gemini",
        "patterns": ["google", "gemini", "长上下文", "多模态", "搜索", "调研", "市场"],
        "reason": "Google 模型能力、调研和长上下文归纳推荐 Gemini CLI。",
    },
    {
        "task_type": "docs",
        "tool": "Hermes",
        "patterns": ["问答", "解释", "总结", "记忆", "知识", "协调", "委托", "delegate"],
        "reason": "通用问答、知识整理和跨 Agent 协调推荐 Hermes。",
    },
]


def read_routing_table() -> str:
    try:
        if ROUTING_TABLE_PATH.exists():
            return ROUTING_TABLE_PATH.read_text(encoding="utf-8", errors="replace")
    except OSError:
        pass
    return ""


def _match_rule(intent: str, context: str) -> dict[str, Any] | None:
    text = f"{intent} {context}".lower()
    for rule in INTENT_RULES:
        if any(pattern.lower() in text for pattern in rule["patterns"]):
            return rule
    return None


def _infer_project(intent: str, context: str) -> str:
    text = f"{intent} {context}".lower()
    projects = list_projects()
    for project in projects:
        name = str(project.get("name", ""))
        if name and name.lower() in text:
            return name
    if "ceo console" in text or "ceo-console" in text:
        return "ceo-console"
    return str(projects[0]["name"]) if projects else "ceo-console"


def _infer_priority(intent: str, context: str) -> str:
    text = f"{intent} {context}".lower()
    if any(k in text for k in ["p0", "紧急", "高优先级", "马上", "立即", "urgent"]):
        return "P0"
    if any(k in text for k in ["p2", "低优先级", "以后", "低"]):
        return "P2"
    return "P1"


def select_tool(intent: str, context: str = "") -> dict[str, Any]:
    rule = _match_rule(intent, context)
    if rule is None:
        task_type = "fullstack"
        route_plan = token_optimized_pipeline(task_type, intent, context, "", "", _infer_project(intent, context), apply_availability=True)
        tool = route_plan.get("primary_tool", "Antigravity")
        reason = format_route_plan_reason(route_plan)
    else:
        task_type = normalize_task_type(rule["task_type"])
        tool = str(rule["tool"])
        reason = str(rule["reason"])
        if not is_allowed_ai_name(tool):
            route_plan = token_optimized_pipeline(task_type, intent, context, "", "", _infer_project(intent, context), apply_availability=True)
            fallback_tool = route_plan.get("primary_tool") or TASK_TYPE_TOOL_ROUTE.get(task_type, ("Codex", ""))[0]
            reason = f"{reason} 当前 {tool} 不在可调度清单，按可用性回退到 {fallback_tool}。"
            tool = fallback_tool
    return {
        "tool": tool,
        "task_type": task_type,
        "reason": reason,
        "routing_table_loaded": bool(read_routing_table()),
    }


def _title_from_intent(intent: str) -> str:
    compact = re.sub(r"\s+", " ", intent).strip()
    return compact[:80] or "AI Commander 派发任务"


def create_and_dispatch_task(intent: str, context: str = "") -> dict[str, Any]:
    intent = intent.strip()
    context = context.strip()
    if not intent:
        raise ValueError("intent is required")

    selection = select_tool(intent, context)
    project = _infer_project(intent, context)
    priority = _infer_priority(intent, context)
    ts = now_str()
    routing_table = read_routing_table()
    notes = "\n\n".join(
        part
        for part in [
            context,
            "来源：AI Commander",
            f"跨工具路由表已读取：{'是' if routing_table else '否'}",
        ]
        if part
    )
    instruction = (
        f"用户自然语言目标：{intent}\n"
        f"上下文：{context or '无'}\n"
        "请按该目标完成可执行交付，并在输出中说明变更、验证结果和后续风险。"
    )

    init_db()
    with closing(db_conn()) as conn:
        cur = conn.execute(
            """
            INSERT INTO tasks
            (title, project, assignee_ai, status, priority, due_at, acceptance_criteria, notes,
             estimated_finish_at, task_type, ai_instruction, locked_scope, expected_output,
             verification_command, routing_reason, execution_state, created_at, updated_at)
            VALUES (?, ?, ?, '待分配', ?, NULL, ?, ?, NULL, ?, ?, '', ?, '', ?, 'idle', ?, ?)
            """,
            (
                _title_from_intent(intent),
                project,
                selection["tool"],
                priority,
                "完成用户目标，提供执行摘要、产物位置、验证命令与结果。",
                notes,
                selection["task_type"],
                instruction,
                "可执行任务结果、验证证据和需要 CEO 决策的事项。",
                selection["reason"],
                ts,
                ts,
            ),
        )
        conn.commit()
        task_id = int(cur.lastrowid)
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()

    append_task_progress(task_id, f"AI Commander 创建任务，选择 {selection['tool']}：{selection['reason']}")
    worker = threading.Thread(target=dispatch_task_worker, args=(task_id,), daemon=True)
    worker.start()
    return {
        "ok": True,
        "tool": selection["tool"],
        "task_id": task_id,
        "reason": selection["reason"],
        "task": row_to_task(row),
        "dispatched": True,
        "routing_table_loaded": selection["routing_table_loaded"],
    }


def commander_status(limit: int = 50) -> dict[str, Any]:
    init_db()
    with closing(db_conn()) as conn:
        reconcile_task_statuses(conn)
        conn.commit()
        rows = fetch_tasks(conn, {"order_by": "updated_at"})[:limit]
    tasks = [row_to_task(r) for r in rows if "AI Commander" in (r["notes"] or "")]
    running = [t for t in tasks if t["execution_state"] == "running"]
    done = [t for t in tasks if t["execution_state"] in {"succeeded", "failed", "unsupported"}]
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "tasks": tasks,
        "running": running,
        "done": done,
        "counts": {"total": len(tasks), "running": len(running), "done": len(done)},
    }
