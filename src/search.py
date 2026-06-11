from __future__ import annotations

import re
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from .config import APP_DIR, DB_PATH
from .db import db_conn, init_db
from .projects import list_projects
from .tools import get_tools_status_cached


ROUTER_PATH = APP_DIR / "frontend" / "src" / "router.ts"
HERMES_MEMORY_PATH = Path.home() / ".hermes" / "memories" / "MEMORY.md"
HERMES_SKILLS_DIR = Path.home() / ".hermes" / "skills"
CLAUDE_AGENTS_DIR = Path.home() / ".claude" / "agents"
RESULT_LIMIT = 12


def unified_search(query: str) -> dict[str, Any]:
    normalized = query.strip()
    return {
        "query": normalized,
        "results": {
            "tasks": _search_tasks(normalized),
            "projects": _search_projects(normalized),
            "memory": _search_memory(normalized),
            "skills": _search_markdown_directory(
                HERMES_SKILLS_DIR, normalized, kind="skill", max_depth=4
            ),
            "agents": _search_markdown_directory(
                CLAUDE_AGENTS_DIR, normalized, kind="agent", max_depth=1
            ),
            "pages": _search_pages(normalized),
            "tools": _search_tools(normalized),
        },
    }


def _matches(query: str, *values: Any) -> bool:
    if not query:
        return True
    needle = query.casefold()
    return any(needle in str(value or "").casefold() for value in values)


def _search_tasks(query: str) -> list[dict[str, Any]]:
    if not DB_PATH.exists():
        return []
    try:
        init_db()
        pattern = f"%{query}%"
        with closing(db_conn()) as conn:
            if query:
                rows = conn.execute(
                    """
                    SELECT id, title, project, status, priority, assignee_ai, due_at, execution_state
                    FROM tasks
                    WHERE title LIKE ?
                       OR project LIKE ?
                       OR status LIKE ?
                       OR priority LIKE ?
                       OR assignee_ai LIKE ?
                       OR notes LIKE ?
                       OR acceptance_criteria LIKE ?
                       OR ai_instruction LIKE ?
                       OR locked_scope LIKE ?
                       OR expected_output LIKE ?
                    ORDER BY
                        CASE priority WHEN 'P0' THEN 0 WHEN 'P1' THEN 1 ELSE 2 END,
                        updated_at DESC
                    LIMIT ?
                    """,
                    (pattern, pattern, pattern, pattern, pattern, pattern, pattern, pattern, pattern, pattern, RESULT_LIMIT),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT id, title, project, status, priority, assignee_ai, due_at, execution_state
                    FROM tasks
                    ORDER BY updated_at DESC
                    LIMIT ?
                    """,
                    (RESULT_LIMIT,),
                ).fetchall()
    except sqlite3.Error:
        return []
    return [dict(row) for row in rows]


def _search_projects(query: str) -> list[dict[str, Any]]:
    try:
        projects = list_projects()
    except Exception:
        return []
    results = []
    for project in projects:
        if _matches(query, project.get("name"), project.get("path"), project.get("description")):
            results.append(
                {
                    "name": project.get("name"),
                    "path": project.get("path"),
                    "status": project.get("status", "active"),
                    "governance_score": project.get("governance_score"),
                }
            )
        if len(results) >= RESULT_LIMIT:
            break
    return results


def _search_memory(query: str) -> list[dict[str, Any]]:
    text = _read_text(HERMES_MEMORY_PATH, limit=300_000)
    if not text:
        return []
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not query:
        matched = lines[-RESULT_LIMIT:]
    else:
        matched = [line for line in lines if query.casefold() in line.casefold()][:RESULT_LIMIT]
    return [{"snippet": _trim(line, 220), "source": "hermes", "path": str(HERMES_MEMORY_PATH)} for line in matched]


def _search_markdown_directory(root: Path, query: str, *, kind: str, max_depth: int) -> list[dict[str, Any]]:
    if not root.exists():
        return []
    results: list[dict[str, Any]] = []
    try:
        files = sorted(
            p for p in root.rglob("*.md") if p.is_file() and len(p.relative_to(root).parts) <= max_depth
        )
    except OSError:
        return []
    for path in files:
        text = _read_text(path, limit=6000)
        name = path.stem
        meta_name = _frontmatter_value(text, "name") or name
        description = _frontmatter_value(text, "description") or _first_body_line(text)
        category = path.relative_to(root).parts[0] if len(path.relative_to(root).parts) > 1 else ""
        if not _matches(query, meta_name, name, description, category, text):
            continue
        item = {
            "name": meta_name,
            "description": _trim(description, 180),
            "path": str(path),
        }
        if kind == "skill":
            item["category"] = category
        results.append(item)
        if len(results) >= RESULT_LIMIT:
            break
    return results


def _search_pages(query: str) -> list[dict[str, Any]]:
    text = _read_text(ROUTER_PATH, limit=80_000)
    if not text:
        return []
    pages: list[dict[str, Any]] = []
    route_re = re.compile(
        r"\{(?P<body>[^{}]*path:\s*\"(?P<path>[^\"]*)\"[^{}]*meta:\s*\{(?P<meta>[^{}]+)\}[^{}]*)\}",
        flags=re.S,
    )
    for match in route_re.finditer(text):
        path = match.group("path")
        meta = match.group("meta")
        body = match.group("body")
        title_match = re.search(r"title:\s*\"([^\"]+)\"", meta)
        group_match = re.search(r"group:\s*\"([^\"]+)\"", meta)
        name_match = re.search(r"name:\s*\"([^\"]+)\"", body)
        title = title_match.group(1) if title_match else path or "home"
        full_path = "/app/" + path.lstrip("/") if path else "/app/"
        page = {"name": title, "path": full_path, "group": group_match.group(1) if group_match else ""}
        if _matches(query, page["name"], page["path"], page["group"], name_match.group(1) if name_match else ""):
            pages.append(page)
        if len(pages) >= RESULT_LIMIT:
            break
    return pages


def _search_tools(query: str) -> list[dict[str, Any]]:
    try:
        status = get_tools_status_cached()
    except Exception:
        status = {}
    results = []
    for name, info in status.items():
        if not _matches(query, name, info.get("command"), info.get("reason"), info.get("acp_target")):
            continue
        results.append(
            {
                "name": name,
                "status": "available" if info.get("available") else "unavailable",
                "available": bool(info.get("available")),
                "runnable": bool(info.get("runnable")),
                "reason": info.get("reason"),
                "command": info.get("command"),
            }
        )
        if len(results) >= RESULT_LIMIT:
            break
    return results


def _read_text(path: Path, *, limit: int) -> str:
    try:
        if path.exists() and path.is_file():
            return path.read_text(encoding="utf-8", errors="replace")[:limit]
    except OSError:
        pass
    return ""


def _frontmatter_value(text: str, key: str) -> str:
    if not text.startswith("---"):
        return ""
    match = re.search(rf"^{re.escape(key)}:\s*(.+)$", text, flags=re.M)
    if not match:
        return ""
    return match.group(1).strip().strip("\"'")


def _first_body_line(text: str) -> str:
    body = re.sub(r"^---.*?---", "", text, flags=re.S).strip()
    for line in body.splitlines():
        line = line.strip().strip("#").strip()
        if line:
            return line
    return ""


def _trim(text: str, max_chars: int) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    return text if len(text) <= max_chars else text[: max_chars - 1] + "..."
