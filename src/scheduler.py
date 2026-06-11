from __future__ import annotations

import json
import os
import shutil
import subprocess
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import DATA_DIR, now_str
from .db import db_conn, init_db


CRON_JOBS = [
    {
        "schedule": "every day 09:00",
        "name": "ceo-daily-brief",
        "endpoint": "daily-brief",
        "prompt": "生成 CEO Console 的每日简报并推送到 http://127.0.0.1:5050/api/cron/daily-brief",
    },
    {
        "schedule": "every 2 hours",
        "name": "ceo-risk-scan",
        "endpoint": "risk-scan",
        "prompt": "扫描项目风险和超期任务，推送到 http://127.0.0.1:5050/api/cron/risk-scan",
    },
    {
        "schedule": "every monday 09:00",
        "name": "ceo-weekly-report",
        "endpoint": "weekly",
        "prompt": "生成本周报告和下周计划，推送到 http://127.0.0.1:5050/api/cron/weekly",
    },
]


def _fallback_cron_dir() -> Path:
    hermes_dir = Path.home() / ".hermes" / "cron"
    if hermes_dir.exists():
        return hermes_dir
    return DATA_DIR / "hermes-cron"


def _job_path(name: str) -> Path:
    safe_name = "".join(ch for ch in name if ch.isalnum() or ch in {"-", "_"}).strip("-_")
    return _fallback_cron_dir() / f"{safe_name or 'cron'}.json"


def _run_hermes_create(job: dict[str, str]) -> dict[str, Any]:
    deliver = f"webhook:http://127.0.0.1:5050/api/cron/{job['endpoint']}"
    cmd = [
        "hermes",
        "cron",
        "create",
        job["schedule"],
        "--name",
        job["name"],
        "--prompt",
        job["prompt"],
        "--deliver",
        deliver,
    ]
    proc = subprocess.run(
        cmd,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=20,
    )
    return {
        "name": job["name"],
        "ok": proc.returncode == 0,
        "mode": "hermes",
        "command": cmd,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "returncode": proc.returncode,
    }


def _write_fallback_job(job: dict[str, str]) -> dict[str, Any]:
    payload = {
        **job,
        "deliver": f"webhook:http://127.0.0.1:5050/api/cron/{job['endpoint']}",
        "registered_at": now_str(),
        "mode": "fallback_file",
    }
    errors: list[str] = []
    for cron_dir in (_fallback_cron_dir(), DATA_DIR / "hermes-cron"):
        try:
            cron_dir.mkdir(parents=True, exist_ok=True)
            safe_name = "".join(ch for ch in job["name"] if ch.isalnum() or ch in {"-", "_"}).strip("-_")
            target = cron_dir / f"{safe_name or 'cron'}.json"
            target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            return {"name": job["name"], "ok": True, "mode": "fallback_file", "path": str(target)}
        except OSError as exc:
            errors.append(f"{cron_dir}: {exc}")
    return {"name": job["name"], "ok": False, "mode": "fallback_file", "errors": errors}


def register_all_crons() -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    hermes_available = shutil.which("hermes") is not None
    for job in CRON_JOBS:
        if hermes_available:
            try:
                result = _run_hermes_create(job)
                if result["ok"]:
                    results.append(result)
                    continue
                result["fallback"] = _write_fallback_job(job)
                results.append(result)
            except Exception as exc:
                fallback = _write_fallback_job(job)
                fallback["error"] = str(exc)
                results.append(fallback)
        else:
            results.append(_write_fallback_job(job))
    return {"ok": all(r.get("ok") or r.get("fallback", {}).get("ok") for r in results), "jobs": results}


def list_crons() -> dict[str, Any]:
    if shutil.which("hermes"):
        try:
            proc = subprocess.run(
                ["hermes", "cron", "list"],
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=15,
            )
            return {
                "ok": proc.returncode == 0,
                "mode": "hermes",
                "stdout": proc.stdout,
                "stderr": proc.stderr,
                "returncode": proc.returncode,
                "fallback_jobs": _list_fallback_jobs(),
            }
        except Exception as exc:
            return {"ok": False, "mode": "hermes", "error": str(exc), "fallback_jobs": _list_fallback_jobs()}
    return {"ok": True, "mode": "fallback_file", "jobs": _list_fallback_jobs()}


def _list_fallback_jobs() -> list[dict[str, Any]]:
    cron_dir = _fallback_cron_dir()
    jobs: list[dict[str, Any]] = []
    if not cron_dir.exists():
        return jobs
    for path in sorted(cron_dir.glob("*.json")):
        try:
            parsed = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(parsed, dict):
                parsed["path"] = str(path)
                jobs.append(parsed)
        except (OSError, json.JSONDecodeError):
            continue
    return jobs


def remove_cron(name: str) -> dict[str, Any]:
    name = name.strip()
    if not name:
        return {"ok": False, "error": "name is required"}
    results: list[dict[str, Any]] = []
    if shutil.which("hermes"):
        for cmd in (["hermes", "cron", "remove", name], ["hermes", "cron", "delete", name]):
            try:
                proc = subprocess.run(
                    cmd,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    capture_output=True,
                    timeout=15,
                )
                results.append(
                    {
                        "command": cmd,
                        "ok": proc.returncode == 0,
                        "stdout": proc.stdout,
                        "stderr": proc.stderr,
                        "returncode": proc.returncode,
                    }
                )
                if proc.returncode == 0:
                    break
            except Exception as exc:
                results.append({"command": cmd, "ok": False, "error": str(exc)})

    path = _job_path(name)
    removed_file = False
    try:
        if path.exists():
            path.unlink()
            removed_file = True
    except OSError as exc:
        results.append({"mode": "fallback_file", "ok": False, "error": str(exc)})
    ok = any(r.get("ok") for r in results) or removed_file
    return {"ok": ok, "name": name, "removed_file": removed_file, "results": results}


def verify_cron_secret(headers: Any, payload: dict[str, Any] | None = None, args: Any = None) -> bool:
    expected = os.getenv("CRON_SECRET", "").strip()
    if not expected:
        return True
    supplied = headers.get("X-Cron-Secret", "") or headers.get("x-cron-secret", "")
    auth = headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        supplied = supplied or auth[7:].strip()
    if not supplied and payload:
        supplied = str(payload.get("secret", ""))
    if not supplied and args is not None:
        supplied = str(args.get("secret", ""))
    return supplied == expected


def ensure_cron_report_table() -> None:
    init_db()
    with closing(db_conn()) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS cron_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                report_type TEXT NOT NULL,
                title TEXT NOT NULL,
                payload TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.commit()


def store_cron_report(report_type: str, title: str, payload: dict[str, Any]) -> dict[str, Any]:
    ensure_cron_report_table()
    created_at = datetime.now().isoformat(timespec="seconds")
    with closing(db_conn()) as conn:
        cur = conn.execute(
            """
            INSERT INTO cron_reports (report_type, title, payload, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (report_type, title, json.dumps(payload, ensure_ascii=False), created_at),
        )
        conn.commit()
    return {"id": cur.lastrowid, "report_type": report_type, "title": title, "created_at": created_at}
