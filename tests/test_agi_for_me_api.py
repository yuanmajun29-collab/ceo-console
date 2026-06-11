from __future__ import annotations

import json
from pathlib import Path

import pytest

import server
import src.agi_for_me as agi


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    task_root = tmp_path / "tasks"
    council_root = tmp_path / "council"
    monkeypatch.setattr(agi, "AGI_TASK_ROOT", task_root)
    monkeypatch.setattr(agi, "COUNCIL_ROOT", council_root)
    with server.app.test_client() as test_client:
        yield test_client, task_root, council_root


def write_task(root: Path, task: dict) -> None:
    path = root / task["id"] / "task.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(task), encoding="utf-8")


def test_lists_tasks_with_council_quorum(client):
    test_client, task_root, council_root = client
    task = {
        "id": "task-1",
        "intent": "评审架构",
        "council_session": "session-1",
        "status": "dispatched",
    }
    write_task(task_root, task)
    session = council_root / "session-1"
    (session / "responses").mkdir(parents=True)
    (session / "manifest.json").write_text(
        json.dumps({"tools": ["codex", "claude-code", "gemini-cli"], "quorum": 3}),
        encoding="utf-8",
    )
    for tool in ("codex", "claude-code", "gemini-cli"):
        (session / "responses" / f"{tool}.md").write_text("ok", encoding="utf-8")

    body = test_client.get("/api/agi-for-me/tasks").get_json()
    assert body["tasks"][0]["council"]["quorum_met"] is True


def test_create_dispatch_and_approve_use_adapter(client, monkeypatch: pytest.MonkeyPatch):
    test_client, _, _ = client
    created = {"id": "task-2", "status": "awaiting_approval"}
    monkeypatch.setattr(server._routes, "agi_create_task", lambda intent, context, project: created)
    monkeypatch.setattr(server._routes, "agi_approve_task", lambda task_id, note: {"id": task_id, "status": "planned"})
    monkeypatch.setattr(server._routes, "agi_dispatch_task", lambda task_id: {"id": task_id, "status": "dispatched"})

    response = test_client.post("/api/agi-for-me/tasks", json={"intent": "签署合同"})
    assert response.status_code == 201
    assert response.get_json()["status"] == "awaiting_approval"

    approved = test_client.post("/api/agi-for-me/tasks/task-2/approve", json={"note": "批准"})
    assert approved.get_json()["status"] == "planned"

    dispatched = test_client.post("/api/agi-for-me/tasks/task-2/dispatch")
    assert dispatched.get_json()["status"] == "dispatched"
