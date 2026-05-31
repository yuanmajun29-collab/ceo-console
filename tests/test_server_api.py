from __future__ import annotations

import json
import subprocess
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path

import pytest

import server


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    data_dir = tmp_path / "data"
    db_path = data_dir / "ceo_console_test.db"
    company_dir = tmp_path / "company"
    company_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(server, "DATA_DIR", data_dir)
    monkeypatch.setattr(server, "DB_PATH", db_path)
    monkeypatch.setattr(server, "_TOOL_STATUS_CACHE", {"ts": None, "data": None})
    monkeypatch.setattr(server, "resolve_company_dir", lambda: (company_dir, "safe_home_company"))
    monkeypatch.setattr(server, "PM_SCRIPT", tmp_path / "pm")

    server.init_db()
    with server.app.test_client() as test_client:
        yield test_client


def _create_task(client, **kwargs):
    payload = {
        "title": kwargs.get("title", "任务A"),
        "project": kwargs.get("project", "proj-a"),
        "assignee_ai": kwargs.get("assignee_ai", "Codex"),
        "status": kwargs.get("status", "待分配"),
        "priority": kwargs.get("priority", "P1"),
        "due_at": kwargs.get("due_at"),
        "acceptance_criteria": kwargs.get("acceptance_criteria", "完成验收"),
        "notes": kwargs.get("notes", "备注"),
    }
    resp = client.post("/api/tasks", json=payload)
    return resp


def _update_task_raw(task_id: int, sql: str, args: tuple):
    with server.db_conn() as conn:
        conn.execute(sql, args + (task_id,))
        conn.commit()


def test_dashboard_route_and_no_cache_header(client):
    # `/` either renders the legacy dashboard (no SPA built) or redirects to /app/
    page = client.get("/")
    assert page.status_code in (200, 302)
    if page.status_code == 200:
        assert "项目工作台" in page.get_data(as_text=True)
    else:
        assert page.headers["Location"].rstrip("/") == "/app"

    # `/legacy` always serves the legacy dashboard so existing flows keep working.
    legacy = client.get("/legacy")
    assert legacy.status_code == 200
    assert "项目工作台" in legacy.get_data(as_text=True)

    health = client.get("/api/health")
    assert health.status_code == 200
    assert "no-store" in health.headers.get("Cache-Control", "")


def test_create_task_and_filter_query(client):
    r1 = _create_task(client, title="网关重构", project="edge-caculate-box", status="待分配")
    r2 = _create_task(client, title="导出优化", project="ccec-timer-system", status="AI执行中", priority="P0")
    assert r1.status_code == 201
    assert r2.status_code == 201

    all_tasks = client.get("/api/tasks").get_json()
    assert len(all_tasks) == 2

    by_project = client.get("/api/tasks?project=edge-caculate-box").get_json()
    assert len(by_project) == 1
    assert by_project[0]["title"] == "网关重构"

    by_status = client.get("/api/tasks?status=AI执行中").get_json()
    assert len(by_status) == 1
    assert by_status[0]["priority"] == "P0"

    by_keyword = client.get("/api/tasks?q=重构").get_json()
    assert len(by_keyword) == 1
    assert by_keyword[0]["project"] == "edge-caculate-box"


def test_create_task_validation(client):
    bad_title = client.post("/api/tasks", json={"title": "", "project": "p1"})
    assert bad_title.status_code == 400
    assert "title is required" in bad_title.get_json()["error"]

    bad_project = client.post("/api/tasks", json={"title": "a", "project": ""})
    assert bad_project.status_code == 400
    assert "project is required" in bad_project.get_json()["error"]

    bad_status = client.post(
        "/api/tasks",
        json={"title": "a", "project": "p1", "status": "invalid"},
    )
    assert bad_status.status_code == 400

    bad_priority = client.post(
        "/api/tasks",
        json={"title": "a", "project": "p1", "priority": "P9"},
    )
    assert bad_priority.status_code == 400


def test_update_and_delete_task(client):
    created = _create_task(client, title="待更新任务")
    task_id = created.get_json()["id"]

    updated = client.patch(
        f"/api/tasks/{task_id}",
        json={"title": "已更新任务", "status": "待人工审查", "priority": "P0"},
    )
    assert updated.status_code == 200
    body = updated.get_json()
    assert body["title"] == "已更新任务"
    assert body["status"] == "待人工审查"
    assert body["priority"] == "P0"

    not_found = client.patch("/api/tasks/999999", json={"title": "x"})
    assert not_found.status_code == 404

    deleted = client.delete(f"/api/tasks/{task_id}")
    assert deleted.status_code == 200
    assert deleted.get_json()["ok"] is True

    deleted_again = client.delete(f"/api/tasks/{task_id}")
    assert deleted_again.status_code == 404


def test_bulk_update_tasks(client):
    t1 = _create_task(client, title="任务1").get_json()["id"]
    t2 = _create_task(client, title="任务2").get_json()["id"]

    bad_ids = client.post("/api/tasks/bulk", json={"ids": "oops", "status": "已完成"})
    assert bad_ids.status_code == 400

    bad_status = client.post("/api/tasks/bulk", json={"ids": [t1, t2], "status": "未知"})
    assert bad_status.status_code == 400

    ok = client.post("/api/tasks/bulk", json={"ids": [t1, t2], "status": "已完成"})
    assert ok.status_code == 200
    assert ok.get_json()["updated_count"] == 2

    rows = client.get("/api/tasks?status=已完成").get_json()
    assert len(rows) == 2


def test_review_flow_approve_and_reject(client):
    task_id = _create_task(client, title="待评审", status="待人工审查").get_json()["id"]

    approve = client.post(f"/api/tasks/{task_id}/review", json={"decision": "approve", "comment": "通过"})
    assert approve.status_code == 200
    assert approve.get_json()["status"] == "已完成"
    assert approve.get_json()["review_result"] == "approved"

    task_id_2 = _create_task(client, title="待驳回", status="待人工审查").get_json()["id"]
    reject = client.post(
        f"/api/tasks/{task_id_2}/review",
        json={"decision": "reject", "comment": "需要补充验证"},
    )
    assert reject.status_code == 200
    assert reject.get_json()["status"] == "待分配"
    assert reject.get_json()["review_result"] == "rejected"
    assert reject.get_json()["review_comment"] == "需要补充验证"

    bad = client.post(f"/api/tasks/{task_id_2}/review", json={"decision": "xxx"})
    assert bad.status_code == 400


def test_dispatch_and_retry_api(client, monkeypatch: pytest.MonkeyPatch):
    task_id = _create_task(client, title="调度测试", assignee_ai="Cursor").get_json()["id"]

    class FakeThread:
        created = []

        def __init__(self, target=None, args=None, daemon=None):
            self.target = target
            self.args = args
            self.daemon = daemon
            self.started = False
            FakeThread.created.append(self)

        def start(self):
            self.started = True

    monkeypatch.setattr(server.threading, "Thread", FakeThread)

    dispatch = client.post(f"/api/tasks/{task_id}/dispatch")
    assert dispatch.status_code == 200
    assert dispatch.get_json()["ok"] is True
    assert len(FakeThread.created) == 1
    assert FakeThread.created[0].args == (task_id,)
    assert FakeThread.created[0].started is True

    _update_task_raw(
        task_id,
        "UPDATE tasks SET execution_state = ?, execution_error = ?, review_result = ?, review_comment = ? WHERE id = ?",
        ("failed", "err", "approved", "old"),
    )
    retry = client.post(f"/api/tasks/{task_id}/retry")
    assert retry.status_code == 200
    assert retry.get_json()["ok"] is True
    assert len(FakeThread.created) == 2

    task = client.get("/api/tasks").get_json()[0]
    assert task["status"] == "待分配"
    assert task["execution_state"] == "idle"
    assert task["execution_error"] is None
    assert task["review_result"] is None
    assert task["assignee_ai"] != "Cursor"
    assert "Token 优先链路" in task["routing_reason"]


def test_dispatch_reject_when_running(client):
    task_id = _create_task(client, title="运行中任务").get_json()["id"]
    _update_task_raw(task_id, "UPDATE tasks SET execution_state = ? WHERE id = ?", ("running",))
    resp = client.post(f"/api/tasks/{task_id}/dispatch")
    assert resp.status_code == 400
    assert "already running" in resp.get_json()["error"]


def test_succeeded_running_task_reconciles_to_review(client):
    task_id = _create_task(client, title="执行完成待同步", status="AI执行中").get_json()["id"]
    _update_task_raw(task_id, "UPDATE tasks SET execution_state = ? WHERE id = ?", ("succeeded",))

    single = client.get(f"/api/tasks/{task_id}")
    assert single.status_code == 200
    assert single.get_json()["status"] == "待人工审查"

    rows = client.get("/api/tasks").get_json()
    assert rows[0]["status"] == "待人工审查"

    summary = client.get("/api/dashboard-summary").get_json()
    assert summary["counts"]["待人工审查"] == 1
    assert summary["counts"]["AI执行中"] == 0


def test_failed_running_task_reconciles_to_todo(client):
    task_id = _create_task(client, title="执行失败待同步", status="AI执行中").get_json()["id"]
    _update_task_raw(task_id, "UPDATE tasks SET execution_state = ?, execution_error = ? WHERE id = ?", ("failed", "boom"))

    single = client.get(f"/api/tasks/{task_id}")
    assert single.status_code == 200
    assert single.get_json()["status"] == "待分配"
    assert single.get_json()["execution_state"] == "failed"

    summary = client.get("/api/dashboard-summary").get_json()
    assert summary["counts"]["待分配"] == 1
    assert summary["counts"]["AI执行中"] == 0


def test_stale_running_task_with_success_log_reconciles_to_review(client, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(server, "get_dispatch_timeout_seconds", lambda: 60)
    task_id = _create_task(client, title="孤儿成功任务", status="AI执行中").get_json()["id"]
    _update_task_raw(
        task_id,
        "UPDATE tasks SET execution_state = ?, execution_started_at = ?, execution_progress = ? WHERE id = ?",
        ("running", "2026-01-01 10:00:00", "[2026-01-01 10:00:00] 进程已启动"),
    )
    logs_dir = server.DATA_DIR / "run-logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    (logs_dir / f"task-{task_id}-20260101-100000.log").write_text(
        '{"result": "success", "stopReason": "stop", "finalAssistantVisibleText": "已完成"}',
        encoding="utf-8",
    )

    single = client.get(f"/api/tasks/{task_id}")
    assert single.status_code == 200
    body = single.get_json()
    assert body["execution_state"] == "succeeded"
    assert body["status"] == "待人工审查"
    assert "孤儿执行已完成" in body["execution_progress"]


def test_stale_running_task_without_success_log_reconciles_to_todo(client, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(server, "get_dispatch_timeout_seconds", lambda: 60)
    task_id = _create_task(client, title="孤儿超时任务", status="AI执行中").get_json()["id"]
    _update_task_raw(
        task_id,
        "UPDATE tasks SET execution_state = ?, execution_started_at = ?, execution_progress = ? WHERE id = ?",
        ("running", "2026-01-01 10:00:00", "[2026-01-01 10:00:00] 进程已启动"),
    )
    logs_dir = server.DATA_DIR / "run-logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    (logs_dir / f"task-{task_id}-20260101-100000.log").write_text("still waiting", encoding="utf-8")

    single = client.get(f"/api/tasks/{task_id}")
    assert single.status_code == 200
    body = single.get_json()
    assert body["execution_state"] == "failed"
    assert body["status"] == "待分配"
    assert "执行监控中断或超时" in body["execution_error"]


def test_task_execution_report_api(client):
    task_id = _create_task(client, title="报告任务", assignee_ai="Codex").get_json()["id"]
    _update_task_raw(
        task_id,
        """
        UPDATE tasks
        SET status = ?,
            execution_state = ?,
            execution_tool = ?,
            execution_started_at = ?,
            execution_finished_at = ?,
            execution_command = ?,
            execution_progress = ?,
            execution_output = ?,
            routing_reason = ?,
            review_result = ?
        WHERE id = ?
        """,
        (
            "已完成",
            "succeeded",
            "Codex",
            "2026-05-19 10:00:00",
            "2026-05-19 10:02:00",
            "/tmp/acp-agent codex exec --sandbox workspace-write prompt",
            "[2026-05-19 10:00:00] 开始执行：cmd\n[2026-05-19 10:02:00] 执行完成：成功\n[2026-05-19 10:03:00] 人工审查通过，任务闭环完成",
            "验证结果：通过",
            "Token 优先链路：Codex。",
            "approved",
        ),
    )

    report = client.get(f"/api/tasks/{task_id}/execution-report")
    assert report.status_code == 200
    body = report.get_json()
    assert body["automation"]["auto_executed"] is True
    assert body["automation"]["auto_routed"] is True
    assert body["automation"]["auto_context_injected"] is True
    assert body["automation"]["human_review_required"] is True
    assert body["automation"]["fully_automatic"] is False
    assert "报告任务" in body["markdown"]

    markdown = client.get(f"/api/tasks/{task_id}/execution-report?format=markdown")
    assert markdown.status_code == 200
    assert "任务执行报告：报告任务" in markdown.get_data(as_text=True)


def test_tasks_export_csv_and_escaping(client):
    _create_task(client, title='包含,逗号"和引号', notes="line1\nline2")
    resp = client.get("/api/tasks/export")
    assert resp.status_code == 200
    assert "tasks.csv" in resp.headers.get("Content-Disposition", "")
    text = resp.get_data(as_text=True)
    assert "id,title,project" in text
    assert '"包含,逗号""和引号"' in text


def test_dashboard_summary_and_daily_brief(client):
    past_due = (datetime.now() - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S")
    soon_due = (datetime.now() + timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")

    t1 = _create_task(client, title="超时任务", status="待分配", due_at=past_due).get_json()["id"]
    _create_task(client, title="即将到期", status="AI执行中", due_at=soon_due)
    _create_task(client, title="待评审1", status="待人工审查")
    _create_task(client, title="待评审2", status="待人工审查")
    _create_task(client, title="待评审3", status="待人工审查")
    _create_task(client, title="待评审4", status="待人工审查")
    _update_task_raw(t1, "UPDATE tasks SET execution_state = ?, execution_error = ? WHERE id = ?", ("failed", "boom"))

    summary = client.get("/api/dashboard-summary")
    assert summary.status_code == 200
    s = summary.get_json()
    assert s["counts"]["待人工审查"] == 4
    assert s["overdue_count"] >= 1
    assert s["failed_dispatch_count"] >= 1

    brief = client.get("/api/daily-brief")
    assert brief.status_code == 200
    b = brief.get_json()
    assert len(b["warnings"]) >= 2
    assert any("超时" in w for w in b["warnings"])
    assert any("审查" in w for w in b["warnings"])
    assert len(b["failed_dispatch_tasks"]) >= 1


def test_projects_endpoints(client, monkeypatch: pytest.MonkeyPatch):
    calls = []

    def fake_run_pm(args, input_text=None):
        calls.append((args, input_text))
        return subprocess.CompletedProcess(args=["pm"], returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(server, "run_pm_command", fake_run_pm)

    p = client.get("/api/projects")
    assert p.status_code == 200
    body = p.get_json()
    assert body["source"] == "safe_home_company"
    assert isinstance(body["projects"], list)

    create = client.post("/api/projects", json={"name": "demo"})
    assert create.status_code == 200
    assert calls[-1][0] == ["new", "demo"]

    archive = client.post("/api/projects/demo/archive")
    assert archive.status_code == 200
    assert calls[-1][0] == ["archive", "demo"]

    unarchive = client.post("/api/projects/demo/unarchive")
    assert unarchive.status_code == 200
    assert calls[-1][0] == ["unarchive", "demo"]

    bad_delete = client.delete("/api/projects/demo", json={"confirm_name": "wrong"})
    assert bad_delete.status_code == 400

    ok_delete = client.delete("/api/projects/demo", json={"confirm_name": "demo"})
    assert ok_delete.status_code == 200
    assert calls[-1][0] == ["delete", "demo"]
    assert calls[-1][1] == "demo\n"


def test_repositories_endpoint(client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    company_dir = tmp_path / "company"
    plain = company_dir / "plain-project"
    git_project = company_dir / "git-project"
    nested_project = company_dir / "nested-project"
    nested_repo = nested_project / "src" / "web"
    plain.mkdir(parents=True, exist_ok=True)
    git_project.mkdir(parents=True, exist_ok=True)
    nested_repo.mkdir(parents=True, exist_ok=True)
    (git_project / ".git").mkdir()
    (nested_repo / ".git").mkdir()

    monkeypatch.setattr(server, "resolve_company_dir", lambda: (company_dir, "safe_home_company"))

    def fake_git(project_path: Path, args: list[str]):
        if "rev-parse" in args:
            return True, "main"
        if "status" in args:
            return True, " M app.py"
        if "remote" in args:
            return True, "git@example.com:demo/git-project.git"
        if "log" in args:
            return True, "abc123|2026-05-17 10:00:00 +0800|init"
        return False, "unsupported"

    monkeypatch.setattr(server, "run_git_command", fake_git)
    resp = client.get("/api/repositories")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["counts"]["total"] == 3
    assert body["counts"]["git"] == 2
    assert body["counts"]["dirty"] == 2
    repos = {repo["name"]: repo for repo in body["repositories"]}
    assert repos["plain-project"]["is_git"] is False
    assert repos["git-project"]["branch"] == "main"
    assert repos["git-project"]["changed_count"] == 1
    assert repos["nested-project/src/web"]["relative_path"] == "src/web"


def test_repository_action_endpoint(client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    company_dir = tmp_path / "company"
    repo = company_dir / "git-project"
    plain = company_dir / "plain-project"
    outside = tmp_path / "outside"
    repo.mkdir(parents=True, exist_ok=True)
    plain.mkdir(parents=True, exist_ok=True)
    outside.mkdir(parents=True, exist_ok=True)
    (repo / ".git").mkdir()
    monkeypatch.setattr(server, "resolve_company_dir", lambda: (company_dir, "safe_home_company"))

    calls: list[tuple[Path, list[str]]] = []

    def fake_git(project_path: Path, args: list[str]):
        calls.append((project_path, args))
        if args == ["status", "--short", "--branch"]:
            return True, "## main\n M app.py"
        if args == ["diff", "--stat"]:
            return True, " app.py | 2 ++"
        if args == ["log", "-5", "--oneline", "--decorate"]:
            return True, "abc123 (HEAD -> main) init"
        if args == ["pull", "--ff-only"]:
            return True, "Already up to date."
        if args == ["add", "-A"]:
            return True, ""
        if args == ["commit", "-m", "feat: update repo"]:
            return True, "[main abc123] feat: update repo"
        if args == ["push"]:
            return True, "pushed"
        if args == ["init"]:
            return True, "Initialized empty Git repository"
        return False, "unsupported"

    monkeypatch.setattr(server, "run_git_command", fake_git)
    status = client.post("/api/repositories/action", json={"path": str(repo), "action": "status"})
    assert status.status_code == 200
    assert status.get_json()["command"] == "git status --short --branch"
    assert " M app.py" in status.get_json()["output"]

    pull = client.post("/api/repositories/action", json={"path": str(repo), "action": "pull"})
    assert pull.status_code == 200
    assert calls[-1] == (repo.resolve(), ["pull", "--ff-only"])

    stage = client.post("/api/repositories/action", json={"path": str(repo), "action": "stage_all"})
    assert stage.status_code == 200
    assert calls[-1] == (repo.resolve(), ["add", "-A"])

    missing_message = client.post("/api/repositories/action", json={"path": str(repo), "action": "commit"})
    assert missing_message.status_code == 400

    commit = client.post(
        "/api/repositories/action",
        json={"path": str(repo), "action": "commit", "message": "feat: update repo"},
    )
    assert commit.status_code == 200
    assert calls[-1] == (repo.resolve(), ["commit", "-m", "feat: update repo"])

    push = client.post("/api/repositories/action", json={"path": str(repo), "action": "push"})
    assert push.status_code == 200
    assert calls[-1] == (repo.resolve(), ["push"])

    init = client.post("/api/repositories/action", json={"path": str(plain), "action": "init"})
    assert init.status_code == 200
    assert calls[-1] == (plain.resolve(), ["init"])

    assert client.post("/api/repositories/action", json={"path": str(plain), "action": "status"}).status_code == 400
    assert client.post("/api/repositories/action", json={"path": str(repo), "action": "reset"}).status_code == 400
    assert client.post("/api/repositories/action", json={"path": str(outside), "action": "status"}).status_code == 400


def test_projects_include_governance_and_operations_report(client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    company_dir = tmp_path / "company"
    project = company_dir / "governed"
    docs = project / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    (project / "CLAUDE.md").write_text("rules", encoding="utf-8")
    (project / ".cursorrules").write_text("rules", encoding="utf-8")
    (docs / "执行清单.md").write_text("- [x] 需求\n- [ ] 测试\n", encoding="utf-8")
    (docs / "ADR-001.md").write_text("# ADR", encoding="utf-8")
    monkeypatch.setattr(server, "resolve_company_dir", lambda: (company_dir, "safe_home_company"))

    projects = client.get("/api/projects")
    assert projects.status_code == 200
    item = projects.get_json()["projects"][0]
    assert item["name"] == "governed"
    assert item["checklist_total"] == 2
    assert item["checklist_done"] == 1
    assert item["adr_count"] == 1
    assert item["governance_score"] > 0

    _create_task(client, title="报表任务", project="governed", status="已完成")
    report = client.get("/api/reports/operations")
    assert report.status_code == 200
    body = report.get_json()
    assert body["projects"]["total"] == 1
    assert body["tasks"]["total"] == 1
    assert body["tasks"]["counts"]["已完成"] == 1


def test_health_endpoint(client, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(server, "resolve_tool_command", lambda tool: f"/usr/local/bin/{tool.lower()}")
    monkeypatch.setattr(server, "launchd_service_status", lambda: {"label": "x", "loaded": True, "pid": "1234"})
    monkeypatch.setattr(server, "get_configured_host", lambda: "127.0.0.1")
    monkeypatch.setattr(server, "get_configured_port", lambda: 5050)
    monkeypatch.setattr(server, "get_dispatch_timeout_seconds", lambda: 3600)

    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.get_json()
    assert "company_dir_in_use" in body
    assert body["runtime_config"]["dispatch_timeout_seconds"] == 3600
    assert body["launchd"]["loaded"] is True
    assert body["tools"]["Cursor"]["available"] is True
    assert "acp" in body


def test_settings_save_reset_and_refresh_tools(client, monkeypatch: pytest.MonkeyPatch):
    initial = client.get("/api/settings")
    assert initial.status_code == 200
    assert initial.get_json()["settings"]["default_task_type"] == "fullstack"

    saved = client.patch(
        "/api/settings",
        json={
            "dispatch_timeout_seconds": 2400,
            "dashboard_refresh_seconds": 30,
            "default_task_type": "docs",
            "default_assignee_ai": "Codex",
            "auto_route_new_tasks": False,
        },
    )
    assert saved.status_code == 200
    settings = saved.get_json()["settings"]
    assert settings["dispatch_timeout_seconds"] == 2400
    assert settings["dashboard_refresh_seconds"] == 30
    assert settings["default_task_type"] == "docs"
    assert settings["default_assignee_ai"] == "Codex"
    assert settings["auto_route_new_tasks"] is False
    assert server.get_dispatch_timeout_seconds() == 2400

    called = {"count": 0}

    def fake_status():
        called["count"] += 1
        return {"Codex": {"available": True, "runnable": True}}

    monkeypatch.setattr(server, "get_tools_status_cached", fake_status)
    refreshed = client.post("/api/settings/refresh-tools")
    assert refreshed.status_code == 200
    assert refreshed.get_json()["tools"]["Codex"]["runnable"] is True
    assert called["count"] == 1

    reset = client.post("/api/settings/reset")
    assert reset.status_code == 200
    assert reset.get_json()["settings"]["dispatch_timeout_seconds"] == server.DEFAULT_DISPATCH_TIMEOUT_SECONDS


def test_tools_status_includes_ai_quota(client, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CEO_CONSOLE_QUOTA_CODEX_REMAINING", "120000")
    monkeypatch.setenv("CEO_CONSOLE_QUOTA_CODEX_LIMIT", "200000")
    monkeypatch.setenv("CEO_CONSOLE_QUOTA_CODEX_UNIT", "tokens")
    monkeypatch.setenv("CEO_CONSOLE_RECHARGE_CODEX_URL", "https://billing.example.test/codex")
    monkeypatch.setattr(server, "resolve_tool_command", lambda tool: f"/usr/bin/{tool.lower().replace(' ', '-')}")
    monkeypatch.setattr(server, "check_command_runnable", lambda path: (True, None))
    server._TOOL_STATUS_CACHE = {"ts": None, "data": None}

    body = client.get("/api/tools/status").get_json()
    quota = body["Codex"]["quota"]
    assert quota["available"] is True
    assert quota["remaining"] == 120000
    assert quota["limit"] == 200000
    assert quota["percent"] == 60
    assert quota["label"] == "120000/200000 tokens"
    assert quota["recharge_url"] == "https://billing.example.test/codex"
    assert body["Gemini"]["quota"]["label"] == "未接入"
    assert body["Gemini"]["quota"]["recharge_url"] == server.DEFAULT_RECHARGE_URLS["Gemini"]


def test_acp_summary_and_dispatch_command(client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    company_dir = tmp_path / "company"
    company_dir.mkdir(parents=True, exist_ok=True)
    acp_agent = company_dir / "acp-agent"
    acp_status = company_dir / "acp-all-status"
    acp_agent.write_text("#!/bin/bash\n", encoding="utf-8")
    acp_status.write_text("#!/bin/bash\n", encoding="utf-8")
    acp_agent.chmod(0o755)
    acp_status.chmod(0o755)
    monkeypatch.setattr(server, "resolve_company_dir", lambda: (company_dir, "safe_home_company"))

    summary = client.get("/api/acp/summary")
    assert summary.status_code == 200
    body = summary.get_json()
    assert body["ok"] is True
    assert body["tools"]["Codex"]["target"] == "codex"

    cmd, err = server.build_tool_run_command("Claude Code", "hello")
    assert err is None
    assert cmd[:3] == [str(acp_agent), "claude", "-p"]


def test_task_type_auto_route_and_routing_rules(client):
    created = client.post(
        "/api/tasks",
        json={
            "title": "设计项目数据模型",
            "project": "proj-a",
            "assignee_ai": "Other",
            "priority": "P1",
            "task_type": "architecture",
            "ai_instruction": "输出架构和数据结构方案",
            "locked_scope": "docs/",
            "expected_output": "架构说明",
            "auto_route": True,
        },
    )
    assert created.status_code == 201
    task = created.get_json()
    assert task["task_type"] == "architecture"
    assert task["assignee_ai"] == "Claude Code"
    assert "架构" in task["routing_reason"]

    rules = client.get("/api/tool-routing-rules")
    assert rules.status_code == 200
    assert rules.get_json()["delivery"]["tool"] == "Codex"

    reroute = client.post(f"/api/tasks/{task['id']}/route")
    assert reroute.status_code == 200
    assert reroute.get_json()["tool"] == "Claude Code"


def test_bulk_dispatch_queues_workers_and_reports_skipped(client, monkeypatch: pytest.MonkeyPatch):
    started: list[int] = []

    class _FakeThread:
        def __init__(self, target, args=(), daemon=False):
            self._target = target
            self._args = args

        def start(self):
            started.append(self._args[0])

    monkeypatch.setattr(server.threading, "Thread", _FakeThread)

    ok = _create_task(client, title="批量任务1", project="proj-a").get_json()
    running = _create_task(client, title="正在跑", project="proj-a").get_json()
    _update_task_raw(running["id"], "UPDATE tasks SET execution_state = ? WHERE id = ?", ("running",))

    resp = client.post(
        "/api/tasks/bulk-dispatch",
        json={"ids": [ok["id"], running["id"], 999_999, ok["id"]]},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert body["queued_count"] == 1
    assert body["queued_ids"] == [ok["id"]]
    skipped_reasons = {s["id"]: s["reason"] for s in body["skipped"]}
    assert "task is already running" in skipped_reasons[running["id"]]
    assert "task not found" in skipped_reasons[999_999]
    # 重复 ID 在 _parse_bulk_ids 中去重，不应出现在 skipped
    assert ok["id"] not in skipped_reasons
    assert started == [ok["id"]]


def test_bulk_dispatch_rejects_bad_input(client):
    assert client.post("/api/tasks/bulk-dispatch", json={"ids": []}).status_code == 400
    assert client.post("/api/tasks/bulk-dispatch", json={"ids": ["abc"]}).status_code == 400
    assert client.post("/api/tasks/bulk-dispatch", json={}).status_code == 400
    too_many = client.post(
        "/api/tasks/bulk-dispatch", json={"ids": list(range(1, server.BULK_DISPATCH_MAX + 2))}
    )
    assert too_many.status_code == 400
    assert "max" in too_many.get_json()["error"].lower()


def test_bulk_retry_resets_state_and_reroutes(client, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(server.threading, "Thread", type(
        "T", (), {"__init__": lambda self, target, args=(), daemon=False: None, "start": lambda self: None}
    ))
    monkeypatch.setattr(
        server,
        "token_optimized_pipeline",
        lambda *a, **kw: {
            "primary_tool": "Codex",
            "recommended_tool": "Codex",
            "reason": "测试路由",
            "pipeline": [{"tool": "Codex"}],
            "execution_pipeline": [{"tool": "Codex"}],
            "skipped_tools": [],
            "fallback_applied": False,
        },
    )

    failed = _create_task(client, title="失败任务", project="proj-a").get_json()
    _update_task_raw(
        failed["id"],
        "UPDATE tasks SET execution_state = ?, execution_error = ?, status = ? WHERE id = ?",
        ("failed", "old error", "AI执行中"),
    )

    resp = client.post("/api/tasks/bulk-retry", json={"ids": [failed["id"]]})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["queued_count"] == 1
    assert body["queued"][0]["tool"] == "Codex"

    refreshed = client.get(f"/api/tasks/{failed['id']}").get_json()
    assert refreshed["status"] == "待分配"
    assert refreshed["execution_state"] == "idle"
    assert refreshed["execution_error"] is None
    assert refreshed["assignee_ai"] == "Codex"


def test_bulk_review_approves_and_rejects(client):
    a = _create_task(client, title="任务A", project="proj-a").get_json()
    b = _create_task(client, title="任务B", project="proj-a").get_json()
    c = _create_task(client, title="任务C", project="proj-a").get_json()
    for task in (a, b):
        _update_task_raw(task["id"], "UPDATE tasks SET status = ? WHERE id = ?", ("待人工审查",))

    # 通过两个待审查 + 一个不在待审查的（应被跳过）
    resp = client.post(
        "/api/tasks/bulk-review",
        json={"ids": [a["id"], b["id"], c["id"]], "decision": "approve", "comment": "批量验收"},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["applied_count"] == 2
    assert set(body["applied_ids"]) == {a["id"], b["id"]}
    assert any(s["id"] == c["id"] for s in body["skipped"])

    refreshed_a = client.get(f"/api/tasks/{a['id']}").get_json()
    assert refreshed_a["status"] == "已完成"
    assert refreshed_a["review_result"] == "approved"
    assert refreshed_a["review_comment"] == "批量验收"

    # 驳回路径
    d = _create_task(client, title="任务D", project="proj-a").get_json()
    _update_task_raw(d["id"], "UPDATE tasks SET status = ? WHERE id = ?", ("待人工审查",))
    reject = client.post(
        "/api/tasks/bulk-review",
        json={"ids": [d["id"]], "decision": "reject", "comment": "需要补充验收"},
    )
    assert reject.status_code == 200
    assert reject.get_json()["applied_count"] == 1
    refreshed_d = client.get(f"/api/tasks/{d['id']}").get_json()
    assert refreshed_d["status"] == "待分配"
    assert refreshed_d["review_result"] == "rejected"


def _drain_sse(client, path: str, max_events: int = 20) -> list[dict]:
    """Collect SSE events from a streaming response until it closes."""
    resp = client.get(path, buffered=False)
    events: list[dict] = []
    current_event: str | None = None
    buffer = ""
    try:
        for chunk in resp.response:
            buffer += chunk.decode("utf-8", errors="replace")
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                line = line.rstrip("\r")
                if not line:
                    current_event = None
                    continue
                if line.startswith(":"):
                    continue
                if line.startswith("event:"):
                    current_event = line.split(":", 1)[1].strip()
                    continue
                if line.startswith("data:"):
                    payload = line[5:].strip()
                    try:
                        data = json.loads(payload) if payload else {}
                    except json.JSONDecodeError:
                        data = {"raw": payload}
                    events.append({"event": current_event or "message", "data": data})
                    if len(events) >= max_events:
                        return events
    finally:
        resp.close()
    return events


def test_log_stream_returns_404_for_missing_task(client):
    resp = client.get("/api/tasks/999999/log-stream")
    assert resp.status_code == 404


def test_log_stream_emits_init_and_done_when_task_finishes(
    client, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    # Make polling instant so the test completes quickly.
    monkeypatch.setattr(server.time, "sleep", lambda *_: None)

    # Build a task that is currently running.
    task = _create_task(client, title="日志流任务", project="proj-a").get_json()
    _update_task_raw(
        task["id"],
        "UPDATE tasks SET execution_state = ?, status = ? WHERE id = ?",
        ("running", "AI执行中"),
    )

    # Drop a fake log file into the data dir (already monkeypatched to tmp_path)
    log_dir = server.DATA_DIR / "run-logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"task-{task['id']}-20260524-120000.log"
    log_file.write_text("initial log line\n", encoding="utf-8")

    # Flip task state to succeeded on the first poll, so the stream terminates.
    call_state = {"count": 0}
    original_conn = server.db_conn

    def stateful_conn():
        conn = original_conn()
        if call_state["count"] == 0:
            call_state["count"] += 1
        elif call_state["count"] == 1:
            # second invocation comes from the state check inside the loop —
            # mark task as succeeded so the stream closes.
            with closing(original_conn()) as c2:
                c2.execute(
                    "UPDATE tasks SET execution_state = 'succeeded' WHERE id = ?",
                    (task["id"],),
                )
                c2.commit()
            call_state["count"] += 1
        return conn

    monkeypatch.setattr(server, "db_conn", stateful_conn)

    events = _drain_sse(client, f"/api/tasks/{task['id']}/log-stream", max_events=8)
    event_names = [e["event"] for e in events]
    assert "init" in event_names
    init = next(e for e in events if e["event"] == "init")
    assert "initial log line" in init["data"]["content"]
    assert "done" in event_names
    done = next(e for e in events if e["event"] == "done")
    assert done["data"]["state"] == "succeeded"


def test_bulk_review_rejects_invalid_decision(client):
    bad = client.post(
        "/api/tasks/bulk-review",
        json={"ids": [1], "decision": "maybe"},
    )
    assert bad.status_code == 400
    assert "decision" in bad.get_json()["error"]


def test_decision_logs_and_command_center(client):
    task_id = _create_task(client, title="待路由任务", project="proj-a").get_json()["id"]
    resp = client.post(
        "/api/decision-logs",
        json={"project": "proj-a", "decision": "本周优先交付 proj-a", "reason": "关键客户验收"},
    )
    assert resp.status_code == 201
    assert resp.get_json()["decision"] == "本周优先交付 proj-a"

    logs = client.get("/api/decision-logs?project=proj-a")
    assert logs.status_code == 200
    assert len(logs.get_json()) == 1

    command = client.get("/api/operations/command-center")
    assert command.status_code == 200
    body = command.get_json()
    assert body["recent_decisions"][0]["project"] == "proj-a"
    assert any(item["action"] == "route_tasks" for item in body["next_actions"])
    assert any(item["id"] == task_id for item in body["unrouted_tasks"])
