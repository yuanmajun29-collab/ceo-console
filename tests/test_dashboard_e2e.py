from __future__ import annotations

import threading
from pathlib import Path

import pytest
from werkzeug.serving import make_server

import server

playwright = pytest.importorskip("playwright.sync_api")


def _launch_chromium_or_skip(p):
    try:
        return p.chromium.launch(headless=True)
    except playwright.Error as exc:
        if "Executable doesn't exist" in str(exc) or "playwright install" in str(exc):
            pytest.skip("Playwright browser binary is not installed")
        raise


@pytest.fixture()
def e2e_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    data_dir = tmp_path / "data"
    db_path = data_dir / "ceo_console_test.db"
    company_dir = tmp_path / "company"
    company_dir.mkdir(parents=True, exist_ok=True)
    (company_dir / "seed-project").mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(server, "DATA_DIR", data_dir)
    monkeypatch.setattr(server, "DB_PATH", db_path)
    monkeypatch.setattr(server, "resolve_company_dir", lambda: (company_dir, "safe_home_company"))

    def fake_pm(args: list[str], input_text: str | None = None):
        cmd = args[0]
        if cmd == "new":
            (company_dir / args[1]).mkdir(parents=True, exist_ok=True)
            return server.subprocess.CompletedProcess(args=args, returncode=0, stdout="ok", stderr="")
        if cmd == "archive":
            name = args[1]
            archive_dir = company_dir / ".archive"
            archive_dir.mkdir(parents=True, exist_ok=True)
            src = company_dir / name
            dst = archive_dir / name
            if src.exists():
                src.rename(dst)
            return server.subprocess.CompletedProcess(args=args, returncode=0, stdout="ok", stderr="")
        if cmd == "unarchive":
            name = args[1]
            archive_dir = company_dir / ".archive"
            src = archive_dir / name
            dst = company_dir / name
            if src.exists():
                src.rename(dst)
            return server.subprocess.CompletedProcess(args=args, returncode=0, stdout="ok", stderr="")
        if cmd == "delete":
            name = args[1]
            p = company_dir / name
            if p.exists():
                p.rmdir()
            return server.subprocess.CompletedProcess(args=args, returncode=0, stdout="ok", stderr="")
        return server.subprocess.CompletedProcess(args=args, returncode=1, stdout="", stderr="unsupported")

    monkeypatch.setattr(server, "run_pm_command", fake_pm)
    monkeypatch.setattr(server, "get_tools_status_cached", lambda: {"Codex": {"available": True, "runnable": True, "command": "/usr/bin/codex", "reason": None}})
    monkeypatch.setattr(server, "launchd_service_status", lambda: {"label": "com.oneperson.ceo-console", "loaded": True, "pid": "1"})

    def fake_dispatch_worker(task_id: int):
        with server.db_conn() as conn:
            conn.execute(
                """
                UPDATE tasks
                SET status = '待人工审查',
                    execution_state = 'succeeded',
                    execution_tool = 'Codex',
                    execution_progress = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                ("[mock] e2e dispatch done", server.now_str(), task_id),
            )
            conn.commit()

    server.init_db()
    httpd = make_server("127.0.0.1", 0, server.app)
    port = httpd.server_port
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    monkeypatch.setattr(server, "dispatch_task_worker", fake_dispatch_worker)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        httpd.shutdown()
        t.join(timeout=2)


def test_dashboard_core_flow(e2e_server):
    with playwright.sync_playwright() as p:
        browser = _launch_chromium_or_skip(p)
        page = browser.new_page()
        page.on("dialog", lambda d: d.accept())

        page.goto(e2e_server, wait_until="domcontentloaded")
        page.wait_for_selector("text=项目工作台")
        page.wait_for_selector("text=工作队列（看板）")

        # 创建项目
        page.fill("#newProjectName", "e2e-project")
        page.click("button:has-text('新建')")
        page.wait_for_timeout(400)
        assert "e2e-project" in page.inner_text("#projectsBody")

        # 创建任务
        page.fill("#newTitle", "E2E任务")
        page.select_option("#newProject", "e2e-project")
        page.select_option("#newAI", "Codex")
        page.click("button:has-text('创建任务')")
        page.wait_for_timeout(500)
        assert "E2E任务" in page.content()

        # 关键区块与导航可见
        page.click(".nav-item:has-text('任务中心')")
        page.wait_for_timeout(200)
        page.wait_for_selector("#taskCenterSection")
        page.wait_for_selector("#colTodo")
        page.wait_for_selector("#toolsSection")

        browser.close()


def test_dashboard_task_close_loop(e2e_server):
    with playwright.sync_playwright() as p:
        browser = _launch_chromium_or_skip(p)
        page = browser.new_page()
        page.on("dialog", lambda d: d.accept())

        page.goto(e2e_server, wait_until="domcontentloaded")
        page.wait_for_selector("text=项目工作台")

        page.fill("#newTitle", "E2E闭环任务")
        page.select_option("#newProject", "seed-project")
        page.select_option("#newAI", "Codex")
        page.click("button:has-text('创建任务')")
        page.wait_for_timeout(400)

        page.locator("#colTodo .task", has_text="E2E闭环任务").first.click()
        page.click("button:has-text('调度执行')")
        page.wait_for_timeout(300)
        page.locator("#taskCenterSection button:has-text('刷新')").click()
        page.wait_for_timeout(300)
        assert "E2E闭环任务" in page.inner_text("#colReview")

        page.fill("#editReviewComment", "E2E自动审查通过")
        page.click("button:has-text('审查通过')")
        page.wait_for_timeout(300)
        page.locator("#taskCenterSection button:has-text('刷新')").click()
        page.wait_for_timeout(300)
        assert "E2E闭环任务" in page.inner_text("#colDone")

        browser.close()
