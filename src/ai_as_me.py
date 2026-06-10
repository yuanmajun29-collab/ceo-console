from __future__ import annotations

import re
import threading
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any

from flask import jsonify, request

from .config import now_str
from .core import app
from .db import db_conn, init_db
from .dispatch import dispatch_task_worker


AI_AS_ME_DIR = Path.home() / "Documents" / "Obsidian Vault" / "02-工作人格与偏好" / "AI-as-Me"
AUTHORITY_PATH = AI_AS_ME_DIR / "authority.yaml"
PROFILE_FILES = (
    AI_AS_ME_DIR / "identity.md",
    AI_AS_ME_DIR / "principles.md",
    AI_AS_ME_DIR / "communication.md",
    Path.home() / ".hermes" / "skills" / "productivity" / "obsidian-shared-knowledge" / "references" / "hermes-user-profile.md",
)

MODES = {"shadow", "copilot", "delegated"}
AUTHORITY_ORDER = {"L0": 0, "L1": 1, "L2": 2, "L3": 3}
MODE_MAX_AUTHORITY = {"shadow": "L0", "copilot": "L1", "delegated": "L2"}

L3_PATTERNS = (
    "付款", "支付", "转账", "采购", "签署", "签合同", "盖章", "公开发布", "发给客户",
    "发送邮件", "删除", "清空", "密码", "token", "密钥", "凭证", "法律承诺", "报价承诺",
)
L2_PATTERNS = (
    "执行", "修改", "更新", "同步", "创建任务", "派发", "运行测试", "部署测试", "整理文档",
)
L1_PATTERNS = ("草拟", "草稿", "回复建议", "方案", "报价草案", "合同草案", "生成内容")


def _ensure_schema() -> None:
    init_db()
    with closing(db_conn()) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ai_as_me_decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                intent TEXT NOT NULL,
                context TEXT,
                recommendation TEXT NOT NULL,
                reasoning TEXT NOT NULL,
                confidence REAL NOT NULL,
                risk_level TEXT NOT NULL,
                authority_level TEXT NOT NULL,
                mode TEXT NOT NULL,
                action_type TEXT NOT NULL,
                execution_status TEXT NOT NULL,
                feedback TEXT,
                feedback_comment TEXT,
                feedback_at TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.commit()


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _parse_authority() -> dict[str, Any]:
    text = _read_text(AUTHORITY_PATH)
    mode_match = re.search(r"(?m)^mode:\s*([a-z]+)\s*$", text)
    mode = mode_match.group(1) if mode_match and mode_match.group(1) in MODES else "shadow"
    allow = re.findall(r"(?m)^\s*-\s*([a-z0-9_-]+)\s*$", text)
    return {
        "mode": mode,
        "max_authority": MODE_MAX_AUTHORITY[mode],
        "auto_execute_actions": allow,
        "source": str(AUTHORITY_PATH),
        "configured": AUTHORITY_PATH.exists(),
    }


def _classify(intent: str) -> tuple[str, str, str]:
    lowered = intent.lower()
    if any(pattern.lower() in lowered for pattern in L3_PATTERNS):
        return "L3", "high", "涉及资金、合同、公开沟通、删除或凭证，必须本人审批。"
    if any(pattern.lower() in lowered for pattern in L2_PATTERNS):
        return "L2", "medium", "属于内部可撤销执行，但需要明确授权范围。"
    if any(pattern.lower() in lowered for pattern in L1_PATTERNS):
        return "L1", "low", "仅生成草稿或方案，不代表本人对外承诺。"
    return "L0", "low", "仅分析和建议，不执行外部动作。"


def _action_type(intent: str, authority: str) -> str:
    lowered = intent.lower()
    if authority == "L3":
        return "restricted_external_action"
    if "创建任务" in lowered or "派发" in lowered:
        return "dispatch_task"
    if authority == "L2":
        return "internal_execution"
    if authority == "L1":
        return "draft"
    return "recommend"


def _recent_feedback(limit: int = 20) -> list[dict[str, Any]]:
    _ensure_schema()
    with closing(db_conn()) as conn:
        rows = conn.execute(
            """
            SELECT intent, recommendation, feedback, feedback_comment
            FROM ai_as_me_decisions
            WHERE feedback IS NOT NULL
            ORDER BY id DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def _confidence(intent: str, feedback: list[dict[str, Any]]) -> float:
    tokens = {token for token in re.split(r"\W+", intent.lower()) if len(token) >= 2}
    similar = 0
    approved = 0
    for item in feedback:
        previous = str(item.get("intent") or "").lower()
        if tokens and any(token in previous for token in tokens):
            similar += 1
            if item.get("feedback") == "approve":
                approved += 1
    if similar == 0:
        return 0.55
    return round(min(0.9, 0.55 + (approved / similar) * 0.25 + min(similar, 5) * 0.02), 2)


def _record_decision(result: dict[str, Any], context: str) -> int:
    _ensure_schema()
    with closing(db_conn()) as conn:
        cur = conn.execute(
            """
            INSERT INTO ai_as_me_decisions
            (intent, context, recommendation, reasoning, confidence, risk_level,
             authority_level, mode, action_type, execution_status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                result["intent"],
                context,
                result["recommendation"],
                result["reasoning"],
                result["confidence"],
                result["risk_level"],
                result["authority_level"],
                result["mode"],
                result["action_type"],
                result["execution_status"],
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        conn.commit()
        return int(cur.lastrowid)


def decide_as_me(intent: str, context: str = "", execute: bool = False) -> dict[str, Any]:
    intent = intent.strip()
    if not intent:
        raise ValueError("intent is required")
    authority = _parse_authority()
    level, risk, classification_reason = _classify(intent)
    action_type = _action_type(intent, level)
    max_level = authority["max_authority"]
    within_mode = AUTHORITY_ORDER[level] <= AUTHORITY_ORDER[max_level]
    explicitly_allowed = action_type in authority["auto_execute_actions"]
    executor_available = action_type == "dispatch_task"
    can_execute = (
        execute
        and authority["mode"] == "delegated"
        and level == "L2"
        and within_mode
        and explicitly_allowed
        and executor_available
    )
    profile_sources = [str(path) for path in PROFILE_FILES if path.exists()]
    feedback = _recent_feedback()
    confidence = _confidence(intent, feedback)
    recommendation = (
        f"按袁马军的工作偏好，建议先给出可验证结果并保留回滚路径：{intent}"
    )
    if level == "L3":
        recommendation = f"准备方案和审批材料，但不要代表本人执行：{intent}"
    result = {
        "intent": intent,
        "recommendation": recommendation,
        "reasoning": classification_reason,
        "confidence": confidence,
        "risk_level": risk,
        "authority_level": level,
        "mode": authority["mode"],
        "mode_max_authority": max_level,
        "action_type": action_type,
        "requires_approval": not can_execute and level != "L0",
        "can_execute": can_execute,
        "execution_status": "authorized" if can_execute else "advice_only",
        "profile_sources": profile_sources,
        "authority_source": authority["source"],
        "policy": {
            "configured": authority["configured"],
            "explicitly_allowed": explicitly_allowed,
            "executor_available": executor_available,
            "high_risk_never_auto_executes": True,
        },
    }
    result["decision_id"] = _record_decision(result, context)
    return result


def record_feedback(decision_id: int, feedback: str, comment: str = "") -> dict[str, Any]:
    if feedback not in {"approve", "reject", "modify"}:
        raise ValueError("feedback must be approve, reject, or modify")
    _ensure_schema()
    with closing(db_conn()) as conn:
        row = conn.execute("SELECT * FROM ai_as_me_decisions WHERE id = ?", (decision_id,)).fetchone()
        if row is None:
            raise KeyError("decision not found")
        conn.execute(
            """
            UPDATE ai_as_me_decisions
            SET feedback = ?, feedback_comment = ?, feedback_at = ?
            WHERE id = ?
            """,
            (feedback, comment or None, datetime.now().isoformat(timespec="seconds"), decision_id),
        )
        conn.commit()
        updated = conn.execute("SELECT * FROM ai_as_me_decisions WHERE id = ?", (decision_id,)).fetchone()
    result = dict(updated)
    _write_feedback_case(result)
    return result


def _write_feedback_case(decision: dict[str, Any]) -> None:
    feedback = str(decision.get("feedback") or "")
    folder = "corrections" if feedback in {"reject", "modify"} else "decision-cases"
    target = AI_AS_ME_DIR / folder / f"decision-{decision['id']}.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    content = "\n".join(
        [
            "---",
            "type: ai-as-me-feedback",
            f"decision_id: {decision['id']}",
            f"feedback: {feedback}",
            f"authority_level: {decision['authority_level']}",
            f"risk_level: {decision['risk_level']}",
            f"created_at: {decision['created_at']}",
            f"feedback_at: {decision.get('feedback_at') or ''}",
            "---",
            "",
            f"# AI as Me 决策反馈 #{decision['id']}",
            "",
            "## 原始意图",
            "",
            str(decision["intent"]),
            "",
            "## AI 建议",
            "",
            str(decision["recommendation"]),
            "",
            "## 本人反馈",
            "",
            str(decision.get("feedback_comment") or feedback),
            "",
        ]
    )
    target.write_text(content, encoding="utf-8")


def ai_as_me_status(limit: int = 20) -> dict[str, Any]:
    authority = _parse_authority()
    _ensure_schema()
    with closing(db_conn()) as conn:
        rows = conn.execute(
            "SELECT * FROM ai_as_me_decisions ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return {
        "mode": authority["mode"],
        "max_authority": authority["max_authority"],
        "authority_source": authority["source"],
        "configured": authority["configured"],
        "profile_sources": [str(path) for path in PROFILE_FILES if path.exists()],
        "recent_decisions": [dict(row) for row in rows],
    }


def _dispatch_authorized_task(intent: str, context: str) -> dict[str, Any]:
    init_db()
    timestamp = now_str()
    with closing(db_conn()) as conn:
        cur = conn.execute(
            """
            INSERT INTO tasks
            (title, project, assignee_ai, status, priority, due_at, acceptance_criteria, notes,
             estimated_finish_at, task_type, ai_instruction, locked_scope, expected_output,
             verification_command, routing_reason, execution_state, created_at, updated_at)
            VALUES (?, 'ceo-console', 'Codex', '待分配', 'P1', NULL, ?, ?, NULL,
                    'delivery', ?, '', ?, '', ?, 'idle', ?, ?)
            """,
            (
                intent[:80],
                "完成授权目标并提供验证证据。",
                f"来源：AI as Me delegated\n{context}",
                f"授权目标：{intent}\n上下文：{context or '无'}",
                "可验证的内部执行结果。",
                "AI as Me L2 明确授权任务派发。",
                timestamp,
                timestamp,
            ),
        )
        conn.commit()
        task_id = int(cur.lastrowid)
    threading.Thread(target=dispatch_task_worker, args=(task_id,), daemon=True).start()
    return {"ok": True, "task_id": task_id, "dispatched": True, "tool": "Codex"}


@app.route("/api/ai-as-me/status", methods=["GET"])
def api_ai_as_me_status():
    return jsonify(ai_as_me_status())


@app.route("/api/ai-as-me/decide", methods=["POST"])
def api_ai_as_me_decide():
    data = request.get_json(force=True, silent=False) or {}
    try:
        decision = decide_as_me(
            str(data.get("intent", "")).strip(),
            str(data.get("context", "")).strip(),
            bool(data.get("execute", False)),
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    if decision["can_execute"]:
        decision["execution"] = _dispatch_authorized_task(
            decision["intent"], str(data.get("context", "")).strip()
        )
        decision["execution_status"] = "dispatched"
    return jsonify(decision)


@app.route("/api/ai-as-me/feedback", methods=["POST"])
def api_ai_as_me_feedback():
    data = request.get_json(force=True, silent=False) or {}
    try:
        feedback = record_feedback(
            int(data.get("decision_id")),
            str(data.get("feedback", "")).strip().lower(),
            str(data.get("comment", "")).strip(),
        )
    except (TypeError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400
    except KeyError as exc:
        return jsonify({"error": str(exc)}), 404
    return jsonify({"ok": True, "decision": feedback})
