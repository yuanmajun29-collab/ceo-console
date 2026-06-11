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

def ensure_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


def init_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                client_name TEXT DEFAULT '',
                budget_cents INTEGER DEFAULT 0,
                status TEXT DEFAULT 'active',
                description TEXT DEFAULT '',
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            )
            """
        )
        ensure_column(conn, "projects", "client_name", "client_name TEXT DEFAULT ''")
        ensure_column(conn, "projects", "budget_cents", "budget_cents INTEGER DEFAULT 0")
        ensure_column(conn, "projects", "status", "status TEXT DEFAULT 'active'")
        ensure_column(conn, "projects", "description", "description TEXT DEFAULT ''")
        ensure_column(conn, "projects", "created_at", "created_at TEXT")
        ensure_column(conn, "projects", "updated_at", "updated_at TEXT")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS clients (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                contact TEXT DEFAULT '',
                notes TEXT DEFAULT '',
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            )
            """
        )
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
        ensure_column(conn, "tasks", "task_type", "task_type TEXT DEFAULT 'fullstack'")
        ensure_column(conn, "tasks", "ai_instruction", "ai_instruction TEXT")
        ensure_column(conn, "tasks", "locked_scope", "locked_scope TEXT")
        ensure_column(conn, "tasks", "expected_output", "expected_output TEXT")
        ensure_column(conn, "tasks", "verification_command", "verification_command TEXT")
        ensure_column(conn, "tasks", "routing_reason", "routing_reason TEXT")
        ensure_column(conn, "tasks", "delivery_evidence", "delivery_evidence TEXT")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS decision_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project TEXT NOT NULL,
                decision TEXT NOT NULL,
                context TEXT,
                reason TEXT,
                impact TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS finance_transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                occurred_on TEXT NOT NULL,
                amount_cents INTEGER NOT NULL,
                currency TEXT NOT NULL DEFAULT 'CNY',
                direction TEXT NOT NULL,
                category TEXT,
                vendor TEXT,
                note TEXT,
                project TEXT,
                source TEXT NOT NULL DEFAULT 'manual',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS finance_subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                vendor TEXT,
                amount_cents INTEGER NOT NULL,
                currency TEXT NOT NULL DEFAULT 'CNY',
                cycle TEXT NOT NULL DEFAULT 'monthly',
                next_renewal_on TEXT,
                status TEXT NOT NULL DEFAULT 'active',
                note TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.commit()


def db_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn
