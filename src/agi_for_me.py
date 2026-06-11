from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from .config import COMPANY_DIR


AGI_ENTRY = Path(os.environ.get("AGI_FOR_ME_ENTRY", str(COMPANY_DIR / "agi-for-me"))).expanduser()
AGI_TASK_ROOT = Path(os.environ.get("AGI_FOR_ME_TASK_ROOT", "~/.company-ai-os/agi-for-me/tasks")).expanduser()
COUNCIL_ROOT = Path(
    os.environ.get(
        "AI_AS_ME_COUNCIL_ROOT",
        "~/Documents/Obsidian Vault/02-工作人格与偏好/AI-as-Me/council",
    )
).expanduser()


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _council_status(session: str | None) -> dict[str, Any] | None:
    if not session:
        return None
    path = COUNCIL_ROOT / session
    manifest_path = path / "manifest.json"
    if not manifest_path.is_file():
        return {"session": session, "available": False, "quorum_met": False}
    manifest = _load_json(manifest_path)
    tools = manifest.get("tools", [])
    responded = [tool for tool in tools if (path / "responses" / f"{tool}.md").is_file()]
    quorum = int(manifest.get("quorum", 0))
    return {
        "session": session,
        "available": True,
        "responded": responded,
        "missing": [tool for tool in tools if tool not in responded],
        "quorum": quorum,
        "quorum_met": len(responded) >= quorum,
    }


def enrich_task(task: dict[str, Any]) -> dict[str, Any]:
    return {**task, "council": _council_status(task.get("council_session"))}


def list_tasks() -> list[dict[str, Any]]:
    tasks = []
    for path in sorted(AGI_TASK_ROOT.glob("*/task.json"), reverse=True):
        try:
            tasks.append(enrich_task(_load_json(path)))
        except (OSError, json.JSONDecodeError):
            continue
    return tasks


def get_task(task_id: str) -> dict[str, Any]:
    path = AGI_TASK_ROOT / task_id / "task.json"
    if not path.is_file():
        raise FileNotFoundError(task_id)
    return enrich_task(_load_json(path))


def run_command(*args: str) -> dict[str, Any]:
    if not AGI_ENTRY.is_file():
        raise FileNotFoundError(f"AGI for Me entry not found: {AGI_ENTRY}")
    result = subprocess.run(
        [str(AGI_ENTRY), "--json", *args],
        cwd=str(COMPANY_DIR),
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=120,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "AGI for Me command failed").strip())
    try:
        return enrich_task(json.loads(result.stdout))
    except json.JSONDecodeError as exc:
        raise RuntimeError("AGI for Me returned invalid JSON") from exc


def create_task(intent: str, context: str = "", project: str = "") -> dict[str, Any]:
    args = ["create", intent]
    if context:
        args.extend(["--context", context])
    if project:
        args.extend(["--project", project])
    return run_command(*args)


def dispatch_task(task_id: str) -> dict[str, Any]:
    return run_command("dispatch", task_id)


def approve_task(task_id: str, note: str = "") -> dict[str, Any]:
    args = ["approve", task_id, "--by", "ceo-console"]
    if note:
        args.extend(["--note", note])
    return run_command(*args)
