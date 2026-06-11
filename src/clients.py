from __future__ import annotations

import sqlite3
from contextlib import closing
from typing import Any

from .config import now_str
from .db import db_conn, init_db
from .projects import get_project_finance, list_projects


def row_to_client(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "contact": row["contact"] or "",
        "notes": row["notes"] or "",
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _client_projects(name: str) -> list[dict[str, Any]]:
    return [project for project in list_projects() if (project.get("client_name") or "") == name]


def _client_finance(projects: list[dict[str, Any]]) -> dict[str, Any]:
    transactions: list[dict[str, Any]] = []
    income_cents = 0
    expense_cents = 0
    for project in projects:
        summary = get_project_finance(project["name"])
        income_cents += summary["income_cents"]
        expense_cents += summary["expense_cents"]
        transactions.extend(summary["transactions"])
    transactions.sort(key=lambda item: (item.get("occurred_on") or "", item.get("id") or 0), reverse=True)
    return {
        "income_cents": income_cents,
        "expense_cents": expense_cents,
        "net_cents": income_cents - expense_cents,
        "transactions": transactions,
    }


def enrich_client(client: dict[str, Any]) -> dict[str, Any]:
    projects = _client_projects(client["name"])
    return {
        **client,
        "projects": projects,
        "project_count": len(projects),
        "finance": _client_finance(projects),
    }


def list_clients() -> list[dict]:
    init_db()
    with closing(db_conn()) as conn:
        rows = conn.execute("SELECT * FROM clients ORDER BY updated_at DESC, name ASC").fetchall()
    return [enrich_client(row_to_client(row)) for row in rows]


def get_client(name: str) -> dict | None:
    init_db()
    with closing(db_conn()) as conn:
        row = conn.execute("SELECT * FROM clients WHERE name = ?", (name,)).fetchone()
    return enrich_client(row_to_client(row)) if row else None


def create_client(payload: dict[str, Any]) -> tuple[dict | None, str | None]:
    name = str(payload.get("name") or "").strip()
    if not name:
        return None, "name is required"
    ts = now_str()
    init_db()
    try:
        with closing(db_conn()) as conn:
            cur = conn.execute(
                """
                INSERT INTO clients (name, contact, notes, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    name,
                    str(payload.get("contact") or "").strip(),
                    str(payload.get("notes") or "").strip(),
                    ts,
                    ts,
                ),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM clients WHERE id = ?", (cur.lastrowid,)).fetchone()
    except sqlite3.IntegrityError:
        return None, "client already exists"
    return enrich_client(row_to_client(row)), None


def update_client(name: str, payload: dict[str, Any]) -> tuple[dict | None, str | None]:
    fields: dict[str, Any] = {}
    if "name" in payload:
        new_name = str(payload.get("name") or "").strip()
        if not new_name:
            return None, "name cannot be empty"
        fields["name"] = new_name
    if "contact" in payload:
        fields["contact"] = str(payload.get("contact") or "").strip()
    if "notes" in payload:
        fields["notes"] = str(payload.get("notes") or "").strip()
    if not fields:
        return None, "no valid fields provided"
    fields["updated_at"] = now_str()
    set_clause = ", ".join(f"{key} = ?" for key in fields)
    init_db()
    try:
        with closing(db_conn()) as conn:
            cur = conn.execute(
                f"UPDATE clients SET {set_clause} WHERE name = ?",
                [*fields.values(), name],
            )
            if cur.rowcount == 0:
                return None, "client not found"
            if "name" in fields:
                conn.execute(
                    "UPDATE projects SET client_name = ?, updated_at = ? WHERE client_name = ?",
                    (fields["name"], fields["updated_at"], name),
                )
            conn.commit()
            lookup = fields.get("name", name)
            row = conn.execute("SELECT * FROM clients WHERE name = ?", (lookup,)).fetchone()
    except sqlite3.IntegrityError:
        return None, "client already exists"
    return enrich_client(row_to_client(row)), None


def delete_client(name: str) -> bool:
    init_db()
    with closing(db_conn()) as conn:
        cur = conn.execute("DELETE FROM clients WHERE name = ?", (name,))
        conn.commit()
        return cur.rowcount > 0
