from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import os
import re
import sqlite3
import urllib.error
import urllib.request
from contextlib import closing
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from .config import (
    DATA_DIR,
    FINANCE_CYCLE_MONTHS,
    FINANCE_CYCLES,
    FINANCE_DIRECTIONS,
    FINANCE_SUBSCRIPTION_STATUSES,
    now_str,
)
from .db import db_conn

RECEIPTS_DIR = DATA_DIR / "finance" / "receipts"

OCR_SUPPORTED_MIME_TYPES = {
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/webp",
    "image/gif",
    "image/heic",
    "image/heif",
    "application/pdf",
}

GEMINI_OCR_PROMPT = """\
你是 CEO Console 的财务票据解析助手。请从这张票据/发票/收据图片中提取以下字段，输出严格的 JSON：

{
  "occurred_on": "YYYY-MM-DD，找不到就留空字符串",
  "amount": "正数小数，例如 128.50，不带货币符号",
  "direction": "out 表示支出（购物、缴费等），in 表示收入（客户付款）",
  "vendor": "对方/商家/客户名称",
  "category": "用中文分类，例如：餐饮 / 差旅 / 服务器 / 订阅 / 服务收入 / 咨询费",
  "currency": "ISO 货币代码，默认 CNY",
  "note": "一句话摘要这笔交易",
  "confidence": "0 到 1 的小数，标识你对整体解析的把握"
}

规则：
- 只输出 JSON，不要解释。
- 找不到的字段用空字符串。
- direction 必须是 "in" 或 "out"。
- amount 不带千分位逗号，不带货币符号。
"""


def _ocr_api_key() -> str | None:
    for key in ("CEO_CONSOLE_GEMINI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        val = os.getenv(key)
        if val:
            return val.strip()
    return None


def _ocr_model() -> str:
    return os.getenv("CEO_CONSOLE_GEMINI_OCR_MODEL", "gemini-2.0-flash").strip()


def is_ocr_configured() -> bool:
    return _ocr_api_key() is not None


def save_receipt_file(content: bytes, mime_type: str, original_name: str = "") -> Path:
    RECEIPTS_DIR.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(content).hexdigest()[:12]
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    ext = _ext_from_mime(mime_type) or _ext_from_name(original_name) or "bin"
    target = RECEIPTS_DIR / f"{ts}-{digest}.{ext}"
    if not target.exists():
        target.write_bytes(content)
    return target


def _ext_from_mime(mime: str) -> str | None:
    return {
        "image/jpeg": "jpg",
        "image/jpg": "jpg",
        "image/png": "png",
        "image/webp": "webp",
        "image/gif": "gif",
        "image/heic": "heic",
        "image/heif": "heif",
        "application/pdf": "pdf",
    }.get(mime.lower())


def _ext_from_name(name: str) -> str | None:
    if not name or "." not in name:
        return None
    ext = name.rsplit(".", 1)[1].lower()
    return ext if re.fullmatch(r"[a-z0-9]{2,5}", ext) else None


def _gemini_url(model: str, key: str) -> str:
    return (
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}"
        f":generateContent?key={key}"
    )


def call_gemini_vision(
    content: bytes, mime_type: str, prompt: str = GEMINI_OCR_PROMPT, timeout: int = 60
) -> tuple[dict[str, Any] | None, str | None]:
    key = _ocr_api_key()
    if not key:
        return None, "Gemini API key not configured"
    body = {
        "contents": [
            {
                "parts": [
                    {"text": prompt},
                    {
                        "inline_data": {
                            "mime_type": mime_type,
                            "data": base64.b64encode(content).decode("ascii"),
                        }
                    },
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.1,
            "responseMimeType": "application/json",
        },
    }
    req = urllib.request.Request(
        _gemini_url(_ocr_model(), key),
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:600]
        return None, f"Gemini HTTP {exc.code}: {detail}"
    except Exception as exc:
        return None, f"Gemini request failed: {exc}"
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None, "Gemini returned non-JSON response"
    return data, None


def _extract_text_from_gemini(data: dict[str, Any]) -> str:
    try:
        return (
            data.get("candidates", [{}])[0]
            .get("content", {})
            .get("parts", [{}])[0]
            .get("text", "")
            or ""
        )
    except (AttributeError, IndexError, TypeError):
        return ""


def _coerce_direction(raw: Any) -> str:
    val = str(raw or "").strip().lower()
    if val in FINANCE_DIRECTIONS:
        return val
    if val in {"expense", "支出", "out_flow", "outgoing"}:
        return "out"
    if val in {"income", "收入", "in_flow", "incoming"}:
        return "in"
    return "out"  # default to expense — receipts are usually expenses


def _coerce_confidence(raw: Any) -> float:
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return 0.5
    if v > 1 and v <= 100:
        v = v / 100
    return max(0.0, min(1.0, v))


def _coerce_amount(raw: Any) -> str | None:
    if raw is None:
        return None
    s = str(raw).strip().replace(",", "").replace("¥", "").replace("￥", "").replace("$", "")
    if not s:
        return None
    cents = parse_money_to_cents(s)
    if cents is None:
        return None
    return f"{cents / 100:.2f}"


def parse_ocr_extracted(text: str) -> dict[str, Any]:
    """Parse the model's JSON string into a normalized dict, with safe fallbacks."""
    parsed: dict[str, Any] = {}
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        # try to salvage embedded JSON
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                parsed = json.loads(match.group(0))
            except json.JSONDecodeError:
                parsed = {}
    occurred_on = parse_iso_date(parsed.get("occurred_on"))
    amount = _coerce_amount(parsed.get("amount"))
    return {
        "occurred_on": occurred_on or "",
        "amount": amount or "",
        "direction": _coerce_direction(parsed.get("direction")),
        "vendor": (parsed.get("vendor") or "").strip(),
        "category": (parsed.get("category") or "").strip(),
        "currency": normalize_currency(parsed.get("currency")),
        "note": (parsed.get("note") or "").strip(),
        "confidence": _coerce_confidence(parsed.get("confidence")),
    }


def ocr_receipt(
    content: bytes, mime_type: str, original_name: str = ""
) -> tuple[dict[str, Any] | None, str | None]:
    """Save receipt + extract fields. Returns (result_dict, error_message)."""
    if not content:
        return None, "empty file"
    if mime_type not in OCR_SUPPORTED_MIME_TYPES:
        return None, f"unsupported mime type: {mime_type}"
    receipt_path = save_receipt_file(content, mime_type, original_name)
    data, err = call_gemini_vision(content, mime_type)
    if err is not None:
        return None, err
    text = _extract_text_from_gemini(data or {})
    extracted = parse_ocr_extracted(text)
    return {
        "receipt_filename": receipt_path.name,
        "receipt_url": f"/api/finance/receipts/{receipt_path.name}",
        "mime_type": mime_type,
        "size_bytes": len(content),
        "extracted": extracted,
        "raw_text": text,
        "model": _ocr_model(),
    }, None


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_AMOUNT_RE = re.compile(r"^-?\d+(?:\.\d{1,4})?$")


def parse_money_to_cents(raw: Any) -> int | None:
    if raw is None:
        return None
    s = str(raw).strip().replace(",", "").replace("¥", "").replace("￥", "").replace("$", "")
    if not s or not _AMOUNT_RE.fullmatch(s):
        return None
    try:
        value = round(float(s) * 100)
    except (TypeError, ValueError):
        return None
    return int(value)


def format_cents(cents: int | None, currency: str = "CNY") -> str:
    if cents is None:
        return "—"
    sign = "-" if cents < 0 else ""
    yuan = abs(cents) / 100
    return f"{sign}{yuan:,.2f} {currency}"


def parse_iso_date(raw: Any) -> str | None:
    if raw is None:
        return None
    s = str(raw).strip()[:10]
    if not s:
        return None
    if not _DATE_RE.fullmatch(s):
        return None
    try:
        datetime.strptime(s, "%Y-%m-%d")
    except ValueError:
        return None
    return s


def normalize_currency(raw: Any) -> str:
    s = str(raw or "CNY").strip().upper()
    return s[:6] if re.fullmatch(r"[A-Z]{2,6}", s) else "CNY"


def row_to_transaction(row: sqlite3.Row) -> dict[str, Any]:
    cents = int(row["amount_cents"])
    return {
        "id": row["id"],
        "occurred_on": row["occurred_on"],
        "amount_cents": cents,
        "amount": cents / 100,
        "amount_label": format_cents(cents, row["currency"]),
        "currency": row["currency"],
        "direction": row["direction"],
        "category": row["category"],
        "vendor": row["vendor"],
        "note": row["note"],
        "project": row["project"],
        "source": row["source"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def row_to_subscription(row: sqlite3.Row) -> dict[str, Any]:
    cents = int(row["amount_cents"])
    cycle = row["cycle"] or "monthly"
    months = FINANCE_CYCLE_MONTHS.get(cycle, 1)
    monthly_equiv = cents // months if months > 0 else 0
    return {
        "id": row["id"],
        "name": row["name"],
        "vendor": row["vendor"],
        "amount_cents": cents,
        "amount": cents / 100,
        "amount_label": format_cents(cents, row["currency"]),
        "currency": row["currency"],
        "cycle": cycle,
        "monthly_equivalent_cents": monthly_equiv,
        "monthly_equivalent_label": format_cents(monthly_equiv, row["currency"]) if months > 0 else "—",
        "next_renewal_on": row["next_renewal_on"],
        "status": row["status"],
        "note": row["note"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def insert_transaction(payload: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    occurred_on = parse_iso_date(payload.get("occurred_on"))
    if not occurred_on:
        return None, "occurred_on must be YYYY-MM-DD"
    cents = parse_money_to_cents(payload.get("amount"))
    if cents is None:
        return None, "amount must be a number"
    direction = str(payload.get("direction", "")).strip().lower()
    if direction not in FINANCE_DIRECTIONS:
        return None, f"direction must be one of {sorted(FINANCE_DIRECTIONS)}"
    currency = normalize_currency(payload.get("currency"))
    ts = now_str()
    with closing(db_conn()) as conn:
        cur = conn.execute(
            """
            INSERT INTO finance_transactions
            (occurred_on, amount_cents, currency, direction, category, vendor, note, project, source, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                occurred_on,
                cents,
                currency,
                direction,
                (payload.get("category") or "").strip() or None,
                (payload.get("vendor") or "").strip() or None,
                (payload.get("note") or "").strip() or None,
                (payload.get("project") or "").strip() or None,
                (payload.get("source") or "manual").strip() or "manual",
                ts,
                ts,
            ),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM finance_transactions WHERE id = ?", (cur.lastrowid,)
        ).fetchone()
    return row_to_transaction(row), None


def list_transactions(filters: dict[str, str] | None = None) -> list[dict[str, Any]]:
    filters = filters or {}
    where: list[str] = []
    args: list[Any] = []
    month = (filters.get("month") or "").strip()
    if month and re.fullmatch(r"\d{4}-\d{2}", month):
        where.append("substr(occurred_on, 1, 7) = ?")
        args.append(month)
    direction = (filters.get("direction") or "").strip().lower()
    if direction in FINANCE_DIRECTIONS:
        where.append("direction = ?")
        args.append(direction)
    category = (filters.get("category") or "").strip()
    if category:
        where.append("category = ?")
        args.append(category)
    project = (filters.get("project") or "").strip()
    if project:
        where.append("project = ?")
        args.append(project)
    sql = "SELECT * FROM finance_transactions"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY occurred_on DESC, id DESC LIMIT 500"
    with closing(db_conn()) as conn:
        rows = conn.execute(sql, args).fetchall()
    return [row_to_transaction(r) for r in rows]


def get_transactions_by_project(project: str) -> list[dict[str, Any]]:
    """Return all transactions linked to a project name."""
    project_name = str(project or "").strip()
    if not project_name:
        return []
    with closing(db_conn()) as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM finance_transactions
            WHERE project = ?
            ORDER BY occurred_on DESC, id DESC
            """,
            (project_name,),
        ).fetchall()
    return [row_to_transaction(r) for r in rows]


def delete_transaction(tid: int) -> bool:
    with closing(db_conn()) as conn:
        cur = conn.execute("DELETE FROM finance_transactions WHERE id = ?", (tid,))
        conn.commit()
        return cur.rowcount > 0


def update_transaction(tid: int, payload: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    """更新交易，只更新提供的字段"""
    fields = {}
    if "occurred_on" in payload:
        d = parse_iso_date(payload["occurred_on"])
        if not d:
            return None, "occurred_on must be YYYY-MM-DD"
        fields["occurred_on"] = d
    if "amount" in payload:
        cents = parse_money_to_cents(payload["amount"])
        if cents is None:
            return None, "amount must be a number"
        fields["amount_cents"] = cents
    if "direction" in payload:
        d = str(payload["direction"]).strip().lower()
        if d not in FINANCE_DIRECTIONS:
            return None, f"direction must be one of {sorted(FINANCE_DIRECTIONS)}"
        fields["direction"] = d
    for key in ("category", "vendor", "note", "project", "currency"):
        if key in payload:
            fields[key] = str(payload[key]).strip() or None
    if not fields:
        return None, "no fields to update"
    fields["updated_at"] = now_str()
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [tid]
    with closing(db_conn()) as conn:
        cur = conn.execute(f"UPDATE finance_transactions SET {set_clause} WHERE id = ?", values)
        conn.commit()
        if cur.rowcount == 0:
            return None, "transaction not found"
        row = conn.execute("SELECT * FROM finance_transactions WHERE id = ?", (tid,)).fetchone()
        return row_to_transaction(row), None


def category_summary(query_month: str | None = None) -> dict[str, Any]:
    """按 category 汇总收入和支出"""
    if not query_month or not re.fullmatch(r"\d{4}-\d{2}", query_month):
        query_month = date.today().strftime("%Y-%m")
    with closing(db_conn()) as conn:
        rows = conn.execute("""
            SELECT direction, category, SUM(amount_cents) as total_cents, COUNT(*) as count
            FROM finance_transactions
            WHERE substr(occurred_on, 1, 7) = ?
            GROUP BY direction, category
            ORDER BY total_cents DESC
        """, (query_month,)).fetchall()
    income = []
    expense = []
    for r in rows:
        item = {"category": r["category"], "total_cents": r["total_cents"], "count": r["count"]}
        if r["direction"] == "in":
            income.append(item)
        else:
            expense.append(item)
    return {"month": query_month, "income": income, "expense": expense}


def monthly_trend(months: int = 6) -> dict[str, Any]:
    """月度收支趋势"""
    with closing(db_conn()) as conn:
        rows = conn.execute("""
            SELECT substr(occurred_on, 1, 7) as ym, direction, SUM(amount_cents) as total_cents
            FROM finance_transactions
            GROUP BY ym, direction
            ORDER BY ym ASC
        """).fetchall()
    by_month: dict[str, dict[str, int]] = {}
    for r in rows:
        ym = r["ym"]
        if ym not in by_month:
            by_month[ym] = {"income": 0, "expense": 0}
        key = "income" if r["direction"] == "in" else "expense"
        by_month[ym][key] += r["total_cents"]
    all_months = sorted(by_month.keys())[-months:]
    return {
        "months": all_months,
        "income": [by_month[m]["income"] for m in all_months],
        "expense": [by_month[m]["expense"] for m in all_months],
        "net": [by_month[m]["income"] - by_month[m]["expense"] for m in all_months],
    }


def insert_subscription(payload: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    name = str(payload.get("name", "")).strip()
    if not name:
        return None, "name is required"
    cents = parse_money_to_cents(payload.get("amount"))
    if cents is None or cents <= 0:
        return None, "amount must be a positive number"
    cycle = str(payload.get("cycle", "monthly")).strip().lower()
    if cycle not in FINANCE_CYCLES:
        return None, f"cycle must be one of {sorted(FINANCE_CYCLES)}"
    status = str(payload.get("status", "active")).strip().lower()
    if status not in FINANCE_SUBSCRIPTION_STATUSES:
        return None, f"status must be one of {sorted(FINANCE_SUBSCRIPTION_STATUSES)}"
    currency = normalize_currency(payload.get("currency"))
    next_renewal = parse_iso_date(payload.get("next_renewal_on"))
    ts = now_str()
    with closing(db_conn()) as conn:
        cur = conn.execute(
            """
            INSERT INTO finance_subscriptions
            (name, vendor, amount_cents, currency, cycle, next_renewal_on, status, note, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                name,
                (payload.get("vendor") or "").strip() or None,
                cents,
                currency,
                cycle,
                next_renewal,
                status,
                (payload.get("note") or "").strip() or None,
                ts,
                ts,
            ),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM finance_subscriptions WHERE id = ?", (cur.lastrowid,)
        ).fetchone()
    return row_to_subscription(row), None


def patch_subscription(sid: int, payload: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    fields: dict[str, Any] = {}
    if "name" in payload:
        name = str(payload["name"]).strip()
        if not name:
            return None, "name cannot be empty"
        fields["name"] = name
    if "vendor" in payload:
        fields["vendor"] = (str(payload["vendor"]).strip() or None)
    if "amount" in payload:
        cents = parse_money_to_cents(payload["amount"])
        if cents is None or cents <= 0:
            return None, "amount must be a positive number"
        fields["amount_cents"] = cents
    if "currency" in payload:
        fields["currency"] = normalize_currency(payload["currency"])
    if "cycle" in payload:
        cycle = str(payload["cycle"]).strip().lower()
        if cycle not in FINANCE_CYCLES:
            return None, f"cycle must be one of {sorted(FINANCE_CYCLES)}"
        fields["cycle"] = cycle
    if "next_renewal_on" in payload:
        nr = parse_iso_date(payload["next_renewal_on"])
        if payload["next_renewal_on"] and not nr:
            return None, "next_renewal_on must be YYYY-MM-DD"
        fields["next_renewal_on"] = nr
    if "status" in payload:
        status = str(payload["status"]).strip().lower()
        if status not in FINANCE_SUBSCRIPTION_STATUSES:
            return None, f"status must be one of {sorted(FINANCE_SUBSCRIPTION_STATUSES)}"
        fields["status"] = status
    if "note" in payload:
        fields["note"] = (str(payload["note"]).strip() or None)
    if not fields:
        return None, "no valid fields provided"
    fields["updated_at"] = now_str()
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [sid]
    with closing(db_conn()) as conn:
        cur = conn.execute(
            f"UPDATE finance_subscriptions SET {set_clause} WHERE id = ?", values
        )
        if cur.rowcount == 0:
            return None, "subscription not found"
        conn.commit()
        row = conn.execute(
            "SELECT * FROM finance_subscriptions WHERE id = ?", (sid,)
        ).fetchone()
    return row_to_subscription(row), None


def delete_subscription(sid: int) -> bool:
    with closing(db_conn()) as conn:
        cur = conn.execute("DELETE FROM finance_subscriptions WHERE id = ?", (sid,))
        conn.commit()
        return cur.rowcount > 0


def list_subscriptions(status: str | None = None) -> list[dict[str, Any]]:
    sql = "SELECT * FROM finance_subscriptions"
    args: list[Any] = []
    if status and status in FINANCE_SUBSCRIPTION_STATUSES:
        sql += " WHERE status = ?"
        args.append(status)
    sql += " ORDER BY status ASC, monthly_equivalent_desc(amount_cents, cycle) DESC"
    # SQLite has no monthly_equivalent_desc helper; sort in Python instead.
    sql = sql.replace(" ORDER BY status ASC, monthly_equivalent_desc(amount_cents, cycle) DESC", " ORDER BY status ASC, amount_cents DESC")
    with closing(db_conn()) as conn:
        rows = conn.execute(sql, args).fetchall()
    return [row_to_subscription(r) for r in rows]


def compute_overview(today: date | None = None) -> dict[str, Any]:
    today = today or date.today()
    current_month_key = today.strftime("%Y-%m")
    prev_month_date = (today.replace(day=1) - timedelta(days=1))
    prev_month_key = prev_month_date.strftime("%Y-%m")

    with closing(db_conn()) as conn:
        all_rows = conn.execute(
            "SELECT occurred_on, amount_cents, direction, currency FROM finance_transactions"
        ).fetchall()
        sub_rows = conn.execute(
            "SELECT amount_cents, cycle, status FROM finance_subscriptions WHERE status = 'active'"
        ).fetchall()

    def month_sum(rows, key, direction):
        return sum(
            r["amount_cents"] for r in rows
            if (r["occurred_on"] or "").startswith(key) and r["direction"] == direction
        )

    current_income = month_sum(all_rows, current_month_key, "in")
    current_expense = month_sum(all_rows, current_month_key, "out")
    prev_income = month_sum(all_rows, prev_month_key, "in")
    prev_expense = month_sum(all_rows, prev_month_key, "out")

    cumulative_in = sum(r["amount_cents"] for r in all_rows if r["direction"] == "in")
    cumulative_out = sum(r["amount_cents"] for r in all_rows if r["direction"] == "out")
    cash_balance = cumulative_in - cumulative_out

    subscription_monthly = 0
    for r in sub_rows:
        months = FINANCE_CYCLE_MONTHS.get(r["cycle"] or "monthly", 1)
        if months > 0:
            subscription_monthly += r["amount_cents"] // months

    # 12 month rolling expense, fall back to current-month expense
    months_back = 12
    cutoff = (today.replace(day=1) - timedelta(days=months_back * 31)).strftime("%Y-%m-%d")
    expense_rows = [
        r for r in all_rows if r["direction"] == "out" and (r["occurred_on"] or "") >= cutoff
    ]
    expense_months: dict[str, int] = {}
    for r in expense_rows:
        k = (r["occurred_on"] or "")[:7]
        expense_months[k] = expense_months.get(k, 0) + r["amount_cents"]
    avg_monthly_expense = (
        sum(expense_months.values()) // len(expense_months) if expense_months else current_expense
    )

    if avg_monthly_expense > 0 and cash_balance > 0:
        runway_months = round(cash_balance / avg_monthly_expense, 1)
    else:
        runway_months = None

    currency = "CNY"
    if all_rows:
        currency = all_rows[0]["currency"] or "CNY"

    has_data = bool(all_rows) or bool(sub_rows)

    return {
        "currency": currency,
        "has_data": has_data,
        "current_month_key": current_month_key,
        "current_month_income_cents": current_income,
        "current_month_expense_cents": current_expense,
        "current_month_net_cents": current_income - current_expense,
        "prev_month_income_cents": prev_income,
        "prev_month_expense_cents": prev_expense,
        "cumulative_income_cents": cumulative_in,
        "cumulative_expense_cents": cumulative_out,
        "cash_balance_cents": cash_balance,
        "subscription_monthly_cents": subscription_monthly,
        "avg_monthly_expense_cents": avg_monthly_expense,
        "runway_months": runway_months,
        "transaction_count": len(all_rows),
        "subscription_count": len(sub_rows),
        "labels": {
            "current_month_income": format_cents(current_income, currency),
            "current_month_expense": format_cents(current_expense, currency),
            "current_month_net": format_cents(current_income - current_expense, currency),
            "cash_balance": format_cents(cash_balance, currency),
            "subscription_monthly": format_cents(subscription_monthly, currency),
            "avg_monthly_expense": format_cents(avg_monthly_expense, currency),
            "runway": f"{runway_months} 月" if runway_months is not None else "—",
        },
    }


CSV_REQUIRED_COLUMNS = {"date", "amount", "direction"}


def import_transactions_from_csv(content: str) -> dict[str, Any]:
    """Parse and bulk-insert transactions from a CSV string.

    Expected columns: date, amount, direction, category, vendor, note, project, currency.
    Returns counts and per-row skip reasons.
    """
    reader = csv.DictReader(io.StringIO(content))
    if not reader.fieldnames:
        return {"imported": 0, "skipped": [], "error": "empty csv"}
    fieldnames = {h.strip().lower() for h in reader.fieldnames}
    missing = CSV_REQUIRED_COLUMNS - fieldnames
    if missing:
        return {
            "imported": 0,
            "skipped": [],
            "error": f"missing required columns: {sorted(missing)}",
        }

    imported = 0
    skipped: list[dict[str, Any]] = []
    for idx, raw_row in enumerate(reader, start=2):  # row 1 is header
        row = {k.strip().lower(): (v.strip() if isinstance(v, str) else v) for k, v in raw_row.items()}
        payload = {
            "occurred_on": row.get("date"),
            "amount": row.get("amount"),
            "direction": row.get("direction"),
            "category": row.get("category"),
            "vendor": row.get("vendor"),
            "note": row.get("note"),
            "project": row.get("project"),
            "currency": row.get("currency") or "CNY",
            "source": "csv",
        }
        inserted, err = insert_transaction(payload)
        if inserted is None:
            skipped.append({"row": idx, "reason": err, "raw": row})
        else:
            imported += 1
    return {"imported": imported, "skipped": skipped, "error": None}
