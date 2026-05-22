from __future__ import annotations

import json
import subprocess
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
    monkeypatch.setattr(server, "SETTINGS_PATH", data_dir / "settings.json")
    monkeypatch.setattr(server, "_TOOL_STATUS_CACHE", {"ts": None, "data": None})
    monkeypatch.setattr(server, "resolve_company_dir", lambda: (company_dir, "safe_home_company"))
    monkeypatch.setattr(server, "PM_SCRIPT", tmp_path / "pm")

    server.init_db()
    with server.app.test_client() as test_client:
        yield test_client


def _create_task(client, **overrides):
    payload = {
        "title": "默认任务",
        "project": "proj-a",
        "assignee_ai": "Codex",
        "status": "待分配",
        "priority": "P1",
    }
    payload.update(overrides)
    return client.post("/api/tasks", json=payload)


def test_api_surface_smoke_matrix(client, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(server, "get_tools_status_cached", lambda: {"Codex": {"available": True, "runnable": True}})
    endpoints = [
        "/api/projects",
        "/api/repositories",
        "/api/reports/operations",
        "/api/tools/status",
        "/api/acp/summary",
        "/api/acp/token-routing",
        "/api/tasks",
        "/api/tasks/export",
        "/api/tool-routing-rules",
        "/api/dashboard-summary",
        "/api/daily-brief",
        "/api/decision-logs",
        "/api/operations/command-center",
        "/api/health",
        "/api/settings",
    ]
    for endpoint in endpoints:
        resp = client.get(endpoint)
        assert resp.status_code == 200, endpoint
        assert "no-store" in resp.headers.get("Cache-Control", ""), endpoint


def test_project_name_validation_blocks_path_traversal(client, monkeypatch: pytest.MonkeyPatch):
    calls: list[list[str]] = []

    def fake_run_pm(args, input_text=None):
        calls.append(args)
        return subprocess.CompletedProcess(args=["pm"], returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(server, "run_pm_command", fake_run_pm)
    bad_names = ["../oops", "a/b", "x\\y", "", "bad name with spaces"]
    for name in bad_names:
        assert client.post("/api/projects", json={"name": name}).status_code == 400
        archive_status = client.post(f"/api/projects/{name}/archive").status_code
        assert archive_status in {400, 404, 405}
    assert calls == []


def test_task_sorting_and_patch_field_matrix(client):
    low = _create_task(client, title="低优先级", priority="P2", due_at="2026-05-22 10:00:00").get_json()
    high = _create_task(client, title="高优先级", priority="P0", due_at="2026-05-21 10:00:00").get_json()
    mid = _create_task(client, title="中优先级", priority="P1", due_at="2026-05-20 10:00:00").get_json()

    by_priority = client.get("/api/tasks?order_by=priority").get_json()
    assert [row["id"] for row in by_priority] == [high["id"], mid["id"], low["id"]]

    by_due = client.get("/api/tasks?order_by=due_at").get_json()
    assert [row["id"] for row in by_due] == [mid["id"], high["id"], low["id"]]

    updated = client.patch(
        f"/api/tasks/{mid['id']}",
        json={
            "assignee_ai": "Gemini",
            "task_type": "security_review",
            "due_at": "",
            "estimated_finish_at": "2026-05-20 12:00:00",
            "notes": "更新备注",
            "verification_command": "pytest",
            "delivery_evidence": "report.json",
        },
    )
    assert updated.status_code == 200
    body = updated.get_json()
    assert body["assignee_ai"] == "Gemini"
    assert body["task_type"] == "security_review"
    assert body["due_at"] is None
    assert body["estimated_finish_at"] == "2026-05-20 12:00:00"
    assert body["verification_command"] == "pytest"
    assert body["delivery_evidence"] == "report.json"

    assert client.patch(f"/api/tasks/{mid['id']}", json={}).status_code == 400
    assert client.patch(f"/api/tasks/{mid['id']}", json={"status": "不存在"}).status_code == 400


def test_auto_route_keyword_overrides_and_unknown_ai_fallback(client):
    security = _create_task(
        client,
        title="接口权限安全审查",
        assignee_ai="Other",
        task_type="fullstack",
        ai_instruction="检查权限漏洞",
        auto_route=True,
    ).get_json()
    assert security["assignee_ai"] == "Gemini"
    assert "Token 优先链路" in security["routing_reason"]
    assert "Codex" in security["routing_reason"]

    unknown_ai = _create_task(client, title="未知 AI", assignee_ai="NotARealTool").get_json()
    assert unknown_ai["assignee_ai"] == "Antigravity"
    assert "Token 优先链路" in unknown_ai["routing_reason"]


def test_review_and_dispatch_error_cases(client):
    task = _create_task(client, title="普通任务").get_json()
    assert client.post("/api/tasks/999999/review", json={"decision": "approve"}).status_code == 404
    assert client.post("/api/tasks/999999/route").status_code == 404
    assert client.post("/api/tasks/999999/dispatch").status_code == 404
    assert client.post("/api/tasks/999999/retry").status_code == 404

    reject = client.post(f"/api/tasks/{task['id']}/review", json={"decision": "reject", "comment": "需要重做"})
    assert reject.status_code == 200
    assert reject.get_json()["status"] == "待分配"
    assert "需要重做" in (reject.get_json()["execution_progress"] or "")


def test_settings_normalization_and_persistence(client):
    saved = client.patch(
        "/api/settings",
        json={
            "dispatch_timeout_seconds": 999999,
            "dashboard_refresh_seconds": -1,
            "default_task_type": "invalid",
            "default_assignee_ai": "invalid",
            "auto_route_new_tasks": "",
            "ignored": "value",
        },
    )
    assert saved.status_code == 200
    settings = saved.get_json()["settings"]
    assert settings["dispatch_timeout_seconds"] == 7200
    assert settings["dashboard_refresh_seconds"] == 5
    assert settings["default_task_type"] == "fullstack"
    assert settings["default_assignee_ai"] == "Other"
    assert settings["auto_route_new_tasks"] is False

    persisted = json.loads(server.SETTINGS_PATH.read_text(encoding="utf-8"))
    assert "ignored" not in persisted
    assert client.get("/api/settings").get_json()["settings"] == settings


def test_acp_status_success_and_failure_modes(client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    company_dir = tmp_path / "company"
    company_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(server, "resolve_company_dir", lambda: (company_dir, "safe_home_company"))

    missing = client.get("/api/acp/status")
    assert missing.status_code == 200
    assert missing.get_json()["ok"] is False
    assert "acp-all-status" in missing.get_json()["stderr"]

    status_script = company_dir / "acp-all-status"
    agent_script = company_dir / "acp-agent"
    status_script.write_text(
        "#!/bin/bash\n"
        "echo '[OK]   Cursor 命令: /usr/bin/cursor'\n"
        "echo '[OK]   Claude context inject: 成功'\n"
        "echo '[OK]   Codex context inject: 成功'\n"
        "echo '[OK]   Gemini context inject: 成功'\n"
        "echo '[OK]   Antigravity context inject: 成功'\n",
        encoding="utf-8",
    )
    agent_script.write_text("#!/bin/bash\n", encoding="utf-8")
    status_script.chmod(0o755)
    agent_script.chmod(0o755)

    ok = client.get("/api/acp/status").get_json()
    assert ok["ok"] is True
    assert ok["scripts"]["agent"]["executable"] is True
    assert ok["tools"]["Cursor"]["configured"] is True
    assert ok["tools"]["Gemini"]["configured"] is True


def test_acp_tool_status_and_command_building(client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    company_dir = tmp_path / "company"
    company_dir.mkdir(parents=True, exist_ok=True)
    agent_script = company_dir / "acp-agent"
    agent_script.write_text("#!/bin/bash\n", encoding="utf-8")
    agent_script.chmod(0o755)
    monkeypatch.setattr(server, "resolve_company_dir", lambda: (company_dir, "safe_home_company"))
    monkeypatch.setattr(server, "resolve_tool_command", lambda tool: f"/usr/bin/{tool.lower().replace(' ', '-')}")
    monkeypatch.setattr(server, "check_command_runnable", lambda path: (True, None))

    tools = client.get("/api/tools/status").get_json()
    assert all(tools[name]["acp_enabled"] is True for name in ["Antigravity", "Claude Code", "Codex", "Gemini", "Cursor"])

    expected = {
        "Claude Code": ["claude", "-p", "--output-format", "text", "hello"],
        "Codex": ["codex", "exec", "--skip-git-repo-check", "--sandbox", "workspace-write", "--color", "never", "hello"],
        "Gemini": ["gemini", "hello"],
        "Antigravity": ["antigravity", "agent", "--local", "--agent", "main", "--message", "hello", "--json"],
    }
    for tool, tail in expected.items():
        cmd, err = server.build_tool_run_command(tool, "hello")
        assert err is None
        assert cmd == [str(agent_script), *tail]

    cmd, err = server.build_tool_run_command("Cursor", "hello")
    assert cmd is None
    assert "交互窗口" in err


def test_dynamic_acp_agent_discovery_and_join(client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    company_dir = tmp_path / "company"
    company_dir.mkdir(parents=True, exist_ok=True)
    status_script = company_dir / "acp-all-status"
    agent_script = company_dir / "acp-agent"
    status_script.write_text(
        "#!/bin/bash\n"
        "echo '[OK]   Qwen Code 命令: /usr/bin/qwen-code'\n"
        "echo '[OK]   Qwen Code context inject: 成功'\n",
        encoding="utf-8",
    )
    agent_script.write_text("#!/bin/bash\n", encoding="utf-8")
    status_script.chmod(0o755)
    agent_script.chmod(0o755)
    monkeypatch.setattr(server, "resolve_company_dir", lambda: (company_dir, "safe_home_company"))

    acp = client.get("/api/acp/status").get_json()
    assert acp["tools"]["Qwen Code"]["configured"] is True
    assert acp["tools"]["Qwen Code"]["target"] == "qwen-code"
    assert acp["tools"]["Qwen Code"]["builtin"] is False

    tools = client.get("/api/tools/status").get_json()
    assert tools["Qwen Code"]["dynamic_acp"] is True
    assert tools["Qwen Code"]["acp_enabled"] is True
    assert tools["Qwen Code"]["runnable"] is True

    settings = client.get("/api/settings").get_json()
    assert "Qwen Code" in settings["allowed"]["assignee_ai"]

    created = _create_task(client, title="动态 Agent 任务", assignee_ai="Qwen Code", auto_route=False).get_json()
    assert created["assignee_ai"] == "Qwen Code"

    cmd, err = server.build_tool_run_command("Qwen Code", "hello")
    assert err is None
    assert cmd == [str(agent_script), "qwen-code", "hello"]


def test_dynamic_acp_agent_deletion_is_removed_from_registry(client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    company_dir = tmp_path / "company"
    company_dir.mkdir(parents=True, exist_ok=True)
    status_script = company_dir / "acp-all-status"
    agent_script = company_dir / "acp-agent"
    agent_script.write_text("#!/bin/bash\n", encoding="utf-8")
    agent_script.chmod(0o755)
    status_script.write_text(
        "#!/bin/bash\n"
        "echo '[OK]   Qwen Code context inject: 成功'\n",
        encoding="utf-8",
    )
    status_script.chmod(0o755)
    monkeypatch.setattr(server, "resolve_company_dir", lambda: (company_dir, "safe_home_company"))
    monkeypatch.setattr(server, "ACP_DISCOVERY_REFRESH_SECONDS", 0)

    connected = client.get("/api/acp/status").get_json()
    assert "Qwen Code" in connected["tools"]

    status_script.write_text(
        "#!/bin/bash\n"
        "echo '[OK]   Cursor context inject: 成功'\n",
        encoding="utf-8",
    )

    summary = client.get("/api/acp/summary").get_json()
    assert "Qwen Code" not in summary["tools"]
    assert "Qwen Code" in summary["discovery"]["removed_tools"]

    tools = client.get("/api/tools/status").get_json()
    assert "Qwen Code" not in tools

    settings = client.get("/api/settings").get_json()
    assert "Qwen Code" not in settings["allowed"]["assignee_ai"]


def test_hermes_agent_discovered_from_project_hook(client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    company_dir = tmp_path / "company"
    hooks_dir = company_dir / ".agent-coordinator" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    (hooks_dir / "hermes.js").write_text("// hermes hook\n", encoding="utf-8")
    agent_script = company_dir / "acp-agent"
    agent_script.write_text("#!/bin/bash\n", encoding="utf-8")
    agent_script.chmod(0o755)
    monkeypatch.setattr(server, "resolve_company_dir", lambda: (company_dir, "safe_home_company"))
    monkeypatch.setattr(server, "resolve_tool_command", lambda tool: "/usr/bin/hermes" if tool == "Hermes" else None)
    monkeypatch.setattr(server, "check_command_runnable", lambda path: (True, None))

    summary = client.get("/api/acp/summary").get_json()
    assert summary["tools"]["Hermes"]["configured"] is True
    assert summary["tools"]["Hermes"]["target"] == "hermes"

    tools = client.get("/api/tools/status").get_json()
    assert tools["Hermes"]["dynamic_acp"] is True
    assert tools["Hermes"]["available"] is True
    assert tools["Hermes"]["runnable"] is True

    settings = client.get("/api/settings").get_json()
    assert "Hermes" in settings["allowed"]["assignee_ai"]

    created = _create_task(client, title="Hermes 任务", assignee_ai="Hermes", auto_route=False).get_json()
    assert created["assignee_ai"] == "Hermes"

    cmd, err = server.build_tool_run_command("Hermes", "hello")
    assert err is None
    assert cmd == ["/usr/bin/hermes", "--accept-hooks", "-z", "hello"]


def test_token_optimized_routing_endpoint_and_task_reason(client):
    small = client.get(
        "/api/acp/token-routing?task_type=security_review&title=小范围权限检查&locked_scope=src/auth.py"
    )
    assert small.status_code == 200
    body = small.get_json()
    assert body["current"]["primary_tool"] == "Gemini"
    assert [step["tool"] for step in body["current"]["pipeline"]] == ["Codex", "Gemini"]
    assert body["current"]["context"]["level"] == "small"
    assert body["tool_profiles"]["Codex"]["cost"] == 1

    large_scope = ",".join(f"file_{idx}.py" for idx in range(12))
    large = client.get(f"/api/acp/token-routing?task_type=market_research&title=竞品分析&locked_scope={large_scope}")
    large_body = large.get_json()
    assert large_body["current"]["context"]["level"] == "large"
    assert large_body["current"]["pipeline"][0]["tool"] == "Codex"

    created = client.post(
        "/api/tasks",
        json={
            "title": "设计核心架构",
            "project": "proj-a",
            "assignee_ai": "Other",
            "task_type": "architecture",
            "auto_route": True,
            "locked_scope": "docs/architecture.md",
        },
    )
    assert created.status_code == 201
    task = created.get_json()
    assert task["assignee_ai"] == "Claude Code"
    assert "Token 优先链路" in task["routing_reason"]
    assert "Codex" in task["routing_reason"]


def test_availability_aware_route_skips_unavailable_primary(client, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        server,
        "get_tools_status_cached",
        lambda: {
            "Claude Code": {"available": False, "runnable": False, "reason": "额度不足"},
            "Gemini": {"available": True, "runnable": True},
            "Codex": {"available": True, "runnable": True},
            "Antigravity": {"available": False, "runnable": False},
            "Cursor": {"available": True, "runnable": False, "reason": "交互模式"},
        },
    )
    created = client.post(
        "/api/tasks",
        json={
            "title": "设计不可用节点容错架构",
            "project": "proj-a",
            "assignee_ai": "Other",
            "task_type": "architecture",
            "auto_route": True,
        },
    )
    assert created.status_code == 201
    task = created.get_json()
    assert task["assignee_ai"] == "Gemini"
    assert "可执行链路" in task["routing_reason"]
    assert "Claude Code" in task["routing_reason"]
    assert "已跳过不可用节点" in task["routing_reason"]


def test_project_profile_adjusts_tool_combination(client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    company_dir = tmp_path / "company"
    backend_project = company_dir / "edge-only"
    fullstack_project = company_dir / "fullstack-app"
    (backend_project / "src" / "gate").mkdir(parents=True, exist_ok=True)
    (fullstack_project / "frontend").mkdir(parents=True, exist_ok=True)
    (fullstack_project / "backend").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(server, "resolve_company_dir", lambda: (company_dir, "safe_home_company"))

    edge_plan = client.get("/api/acp/token-routing?project=edge-only&task_type=fullstack&locked_scope=src/gate/config.py").get_json()
    assert edge_plan["current"]["project_profile"]["archetype"] == "edge"
    assert edge_plan["current"]["project_profile"]["scope_domains"] == ["backend", "edge"]
    assert edge_plan["current"]["primary_tool"] == "Codex"
    assert [step["tool"] for step in edge_plan["current"]["pipeline"]] == ["Codex", "Claude Code"]

    fullstack_plan = client.get("/api/acp/token-routing?project=fullstack-app&task_type=fullstack").get_json()
    assert fullstack_plan["current"]["project_profile"]["archetype"] == "fullstack"
    assert fullstack_plan["current"]["primary_tool"] == "Antigravity"
    assert [step["tool"] for step in fullstack_plan["current"]["pipeline"]] == ["Codex", "Antigravity"]

    security_plan = client.get("/api/acp/token-routing?project=edge-only&task_type=security_review&locked_scope=src/gate").get_json()
    assert security_plan["current"]["primary_tool"] == "Gemini"
    assert [step["tool"] for step in security_plan["current"]["pipeline"]] == ["Codex", "Gemini"]

    scoped_edge_in_fullstack = client.get("/api/acp/token-routing?project=fullstack-app&task_type=fullstack&locked_scope=src/gate/config.py").get_json()
    assert scoped_edge_in_fullstack["current"]["project_profile"]["archetype"] == "edge"
    assert scoped_edge_in_fullstack["current"]["primary_tool"] == "Codex"


def test_repository_git_error_and_clean_state(client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    company_dir = tmp_path / "company"
    project = company_dir / "repo"
    project.mkdir(parents=True, exist_ok=True)
    (project / ".git").mkdir()
    monkeypatch.setattr(server, "resolve_company_dir", lambda: (company_dir, "safe_home_company"))

    def fake_git(path: Path, args: list[str]):
        if "rev-parse" in args:
            return False, "not a branch"
        if "status" in args:
            return True, ""
        if "remote" in args:
            return False, "no origin"
        if "log" in args:
            return False, "no commits"
        return False, "bad"

    monkeypatch.setattr(server, "run_git_command", fake_git)
    repo = client.get("/api/repositories").get_json()["repositories"][0]
    assert repo["is_git"] is True
    assert repo["dirty"] is False
    assert repo["status"] == "干净"
    assert repo["error"] == "not a branch"
    assert repo["remote"] is None


def test_command_center_action_priority_matrix(client):
    failed = _create_task(client, title="失败任务", status="AI执行中", priority="P0").get_json()
    review = _create_task(client, title="评审任务", status="待人工审查").get_json()
    overdue = _create_task(client, title="超时任务", due_at="2000-01-01 00:00:00").get_json()
    unrouted = _create_task(client, title="待路由", assignee_ai="Codex").get_json()

    with server.db_conn() as conn:
        conn.execute("UPDATE tasks SET execution_state = 'failed', execution_error = 'boom' WHERE id = ?", (failed["id"],))
        conn.execute("UPDATE tasks SET routing_reason = '' WHERE id = ?", (unrouted["id"],))
        conn.commit()

    body = client.get("/api/operations/command-center").get_json()
    actions = [item["action"] for item in body["next_actions"]]
    assert actions[:3] == ["review_queue", "fix_failed_dispatch", "resolve_overdue"]
    assert "route_tasks" in actions
    assert any(t["id"] == review["id"] for t in body["review_queue"])
    assert any(t["id"] == overdue["id"] for t in body["overdue_tasks"])


def test_frontend_contract_contains_all_core_modules():
    html = (server.APP_DIR / "templates" / "dashboard.html").read_text(encoding="utf-8")
    assert "额度剩余" in html
    assert "充值 / 查看用量" in html
    required_ids = [
        "projectsBody",
        "toolRows",
        "acpStatusPill",
        "acpToolRows",
        "tokenRoutingChain",
        "opsRows",
        "decisionRows",
        "reportRows",
        "settingsSummary",
        "settingsDiagnostics",
        "settingsRows",
        "analyticsBars",
        "repoOps",
        "repoRows",
        "colTodo",
        "colWrapTodo",
        "summaryTodo",
        "colRunning",
        "colWrapRunning",
        "summaryRunning",
        "colReview",
        "colWrapReview",
        "summaryReview",
        "colDone",
        "colWrapDone",
        "summaryDone",
        "detailLog",
        "detailFailureField",
        "detailFailureBox",
    ]
    for element_id in required_ids:
        assert f'id="{element_id}"' in html

    required_functions = [
        "loadAll",
        "createTask",
        "saveTask",
        "routeTask",
        "dispatchTask",
        "retryTask",
        "reviewTask",
        "createProject",
        "createDecisionLog",
        "downloadOpsReport",
        "saveSettings",
        "loadRepositories",
        "repoAction",
        "loadAcpStatus",
        "renderAnalytics",
        "quotaHtml",
        "effectiveTaskStatus",
        "taskFailureReason",
        "refreshSelectedTaskDetail",
        "toggleBoardColumn",
        "setBoardCollapsed",
        "scrollToSection",
        "activateNavItem",
    ]
    for fn in required_functions:
        assert f"function {fn}" in html or f"async function {fn}" in html
