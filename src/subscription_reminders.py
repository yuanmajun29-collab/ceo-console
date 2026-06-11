from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from .config import DB_PATH

SUBSCRIPTION_REMINDERS_SCHEMA = """
CREATE TABLE IF NOT EXISTS subscription_reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tool_name TEXT NOT NULL,
    provider TEXT NOT NULL,
    plan_name TEXT,
    renewal_date TEXT,
    renewal_url TEXT,
    amount_cents INTEGER,
    remind_days_before INTEGER DEFAULT 7,
    notes TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
)
"""

DEFAULT_REMINDERS = [
    ("Hermes", "DeepSeek", "https://platform.deepseek.com/usage"),
    ("PilotDeck", "DeepSeek", "https://platform.deepseek.com/usage"),
    ("Claude Code", "Anthropic", "https://claude.ai/plans"),
    ("Codex", "OpenAI", "https://chatgpt.com/"),
    ("Cursor", "Cursor", "https://cursor.com/pricing"),
    ("Gemini CLI", "Google", "https://aistudio.google.com/"),
]


def _today() -> date:
    return date.today()


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _default_renewal_date() -> str:
    return (_today() + timedelta(days=7)).isoformat()


def _connect() -> sqlite3.Connection:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute(SUBSCRIPTION_REMINDERS_SCHEMA)
    _seed_defaults(conn)
    conn.commit()
    return conn


def _seed_defaults(conn: sqlite3.Connection) -> None:
    count = conn.execute("SELECT COUNT(*) FROM subscription_reminders").fetchone()[0]
    if count:
        return
    ts = _now()
    renewal_date = _default_renewal_date()
    conn.executemany(
        """
        INSERT INTO subscription_reminders (
            tool_name, provider, plan_name, renewal_date, renewal_url,
            amount_cents, remind_days_before, notes, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (tool, provider, None, renewal_date, url, None, 7, "默认续费提醒，可在 UI 中修改。", ts, ts)
            for tool, provider, url in DEFAULT_REMINDERS
        ],
    )


def init_subscription_reminders() -> None:
    with closing(_connect()):
        pass


def _parse_renewal_date(value: Any) -> str | None:
    if value is None or str(value).strip() == "":
        return None
    text = str(value).strip()
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError as exc:
        raise ValueError("renewal_date must be YYYY-MM-DD") from exc


def _parse_optional_int(value: Any, field: str, *, minimum: int | None = None) -> int | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be an integer") from exc
    if minimum is not None and parsed < minimum:
        raise ValueError(f"{field} must be >= {minimum}")
    return parsed


def _clean_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _days_until(renewal_date: str | None) -> int | None:
    if not renewal_date:
        return None
    try:
        target = date.fromisoformat(renewal_date)
    except ValueError:
        return None
    return (target - _today()).days


def _row_to_reminder(row: sqlite3.Row) -> dict[str, Any]:
    days_until = _days_until(row["renewal_date"])
    if days_until is None:
        status = "unscheduled"
        level = "info"
        status_label = "未设置续费日"
    elif days_until < 0:
        status = "expired"
        level = "high"
        status_label = f"已过期 {abs(days_until)} 天"
    elif days_until == 0:
        status = "due_today"
        level = "high"
        status_label = "今天到期"
    elif days_until <= int(row["remind_days_before"] or 7):
        status = "due_soon"
        level = "warning"
        status_label = f"{days_until} 天后到期"
    else:
        status = "upcoming"
        level = "info"
        status_label = f"{days_until} 天后到期"
    return {
        "id": row["id"],
        "tool_name": row["tool_name"],
        "provider": row["provider"],
        "plan_name": row["plan_name"],
        "renewal_date": row["renewal_date"],
        "renewal_url": row["renewal_url"],
        "amount_cents": row["amount_cents"],
        "remind_days_before": int(row["remind_days_before"] or 7),
        "notes": row["notes"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "days_until": days_until,
        "status": status,
        "level": level,
        "status_label": status_label,
    }


def list_subscription_reminders() -> list[dict[str, Any]]:
    with closing(_connect()) as conn:
        rows = conn.execute(
            """
            SELECT * FROM subscription_reminders
            ORDER BY
                CASE WHEN renewal_date IS NULL THEN 1 ELSE 0 END,
                renewal_date ASC,
                tool_name ASC
            """
        ).fetchall()
    return [_row_to_reminder(row) for row in rows]


def upsert_subscription_reminder(payload: dict[str, Any]) -> dict[str, Any]:
    reminder_id = _parse_optional_int(payload.get("id"), "id", minimum=1)
    tool_name = _clean_text(payload.get("tool_name"))
    provider = _clean_text(payload.get("provider"))
    if not tool_name:
        raise ValueError("tool_name is required")
    if not provider:
        raise ValueError("provider is required")

    plan_name = _clean_text(payload.get("plan_name"))
    renewal_date = _parse_renewal_date(payload.get("renewal_date"))
    renewal_url = _clean_text(payload.get("renewal_url"))
    amount_cents = _parse_optional_int(payload.get("amount_cents"), "amount_cents", minimum=0)
    remind_days_before = _parse_optional_int(
        payload.get("remind_days_before", 7), "remind_days_before", minimum=0
    )
    notes = _clean_text(payload.get("notes"))
    ts = _now()

    with closing(_connect()) as conn:
        if reminder_id:
            existing = conn.execute(
                "SELECT id FROM subscription_reminders WHERE id = ?", (reminder_id,)
            ).fetchone()
            if not existing:
                raise KeyError("subscription reminder not found")
            conn.execute(
                """
                UPDATE subscription_reminders
                SET tool_name = ?, provider = ?, plan_name = ?, renewal_date = ?,
                    renewal_url = ?, amount_cents = ?, remind_days_before = ?,
                    notes = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    tool_name,
                    provider,
                    plan_name,
                    renewal_date,
                    renewal_url,
                    amount_cents,
                    remind_days_before,
                    notes,
                    ts,
                    reminder_id,
                ),
            )
        else:
            cur = conn.execute(
                """
                INSERT INTO subscription_reminders (
                    tool_name, provider, plan_name, renewal_date, renewal_url,
                    amount_cents, remind_days_before, notes, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tool_name,
                    provider,
                    plan_name,
                    renewal_date,
                    renewal_url,
                    amount_cents,
                    remind_days_before,
                    notes,
                    ts,
                    ts,
                ),
            )
            reminder_id = int(cur.lastrowid)
        conn.commit()
        row = conn.execute("SELECT * FROM subscription_reminders WHERE id = ?", (reminder_id,)).fetchone()
    return _row_to_reminder(row)


def delete_subscription_reminder(reminder_id: int) -> bool:
    with closing(_connect()) as conn:
        cur = conn.execute("DELETE FROM subscription_reminders WHERE id = ?", (reminder_id,))
        conn.commit()
        return cur.rowcount > 0


def get_due_reminders(days: int = 7) -> list[dict[str, Any]]:
    horizon = _today() + timedelta(days=days)
    with closing(_connect()) as conn:
        rows = conn.execute(
            """
            SELECT * FROM subscription_reminders
            WHERE renewal_date IS NOT NULL
              AND date(renewal_date) <= date(?)
              AND date(renewal_date, '-' || COALESCE(remind_days_before, 7) || ' days') <= date(?)
            ORDER BY date(renewal_date) ASC, tool_name ASC
            """,
            (horizon.isoformat(), _today().isoformat()),
        ).fetchall()
    return [_row_to_reminder(row) for row in rows]


def get_subscription_expiry_risks(days: int = 7) -> list[dict[str, Any]]:
    risks: list[dict[str, Any]] = []
    for reminder in get_due_reminders(days):
        status = reminder["status"]
        level = "high" if status in {"expired", "due_today"} else "warning"
        risks.append(
            {
                "type": "subscription_expiry",
                "level": level,
                "tool": reminder["tool_name"],
                "provider": reminder["provider"],
                "renewal_date": reminder["renewal_date"],
                "days_until": reminder["days_until"],
                "renewal_url": reminder["renewal_url"],
                "message": f"{reminder['tool_name']} 订阅{reminder['status_label']}",
                "suggestion": "打开续费链接确认额度、账单或套餐状态。",
                "reminder_id": reminder["id"],
            }
        )
    return risks
