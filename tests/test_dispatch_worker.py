from __future__ import annotations

from pathlib import Path

import pytest

import server


@pytest.fixture()
def isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    data_dir = tmp_path / "data"
    db_path = data_dir / "ceo_console_test.db"
    company_dir = tmp_path / "company"
    project_dir = company_dir / "proj-a"
    project_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(server, "DATA_DIR", data_dir)
    monkeypatch.setattr(server, "DB_PATH", db_path)
    monkeypatch.setattr(server, "resolve_company_dir", lambda: (company_dir, "safe_home_company"))
    server.init_db()
    yield


def _new_task(title: str = "调度任务", assignee_ai: str = "Codex") -> int:
    with server.db_conn() as conn:
        ts = server.now_str()
        cur = conn.execute(
            """
            INSERT INTO tasks
            (title, project, assignee_ai, status, priority, due_at, acceptance_criteria, notes,
             estimated_finish_at, execution_state, created_at, updated_at)
            VALUES (?, ?, ?, '待分配', 'P1', NULL, ?, ?, NULL, 'idle', ?, ?)
            """,
            (title, "proj-a", assignee_ai, "通过", "备注", ts, ts),
        )
        conn.commit()
        return int(cur.lastrowid)


def _task(task_id: int) -> dict:
    with server.db_conn() as conn:
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return server.row_to_task(row)


def test_dispatch_worker_success_path(isolated_env, monkeypatch: pytest.MonkeyPatch):
    task_id = _new_task()

    monkeypatch.setattr(server, "build_tool_run_command", lambda tool, prompt: (["fake-cli", prompt], None))
    monkeypatch.setattr(server.time, "sleep", lambda *_: None)

    class FakePopen:
        def __init__(self, cmd, cwd, text, encoding, errors, stdout, stderr):
            self.returncode = None
            self._poll_count = 0
            self.pid = 12345
            stdout.write("running line\n")
            stdout.flush()

        def poll(self):
            self._poll_count += 1
            if self._poll_count == 1:
                return None
            self.returncode = 0
            return 0

        def kill(self):
            self.returncode = -9

        def wait(self, timeout=None):
            return self.returncode

    monkeypatch.setattr(server.subprocess, "Popen", FakePopen)
    server.dispatch_task_worker(task_id)
    after = _task(task_id)
    assert after["execution_state"] == "succeeded"
    assert after["status"] == "待人工审查"
    assert "running line" in (after["execution_output"] or "")
    assert after["execution_error"] is None


def test_dispatch_worker_auto_fallback(isolated_env, monkeypatch: pytest.MonkeyPatch):
    task_id = _new_task(assignee_ai="Cursor")

    def fake_build(tool, prompt):
        if tool == "Cursor":
            return None, "cursor 不支持无头"
        return ["fallback-cli", prompt], None

    monkeypatch.setattr(server, "build_tool_run_command", fake_build)
    monkeypatch.setattr(server, "pick_fallback_tool", lambda preferred_tools=None: ("Claude Code", None))
    monkeypatch.setattr(server.time, "sleep", lambda *_: None)

    class FakePopen:
        def __init__(self, cmd, cwd, text, encoding, errors, stdout, stderr):
            self.returncode = None
            self._poll_count = 0
            self.pid = 22345
            stdout.write("fallback ok\n")
            stdout.flush()

        def poll(self):
            self._poll_count += 1
            if self._poll_count == 1:
                return None
            self.returncode = 0
            return 0

        def kill(self):
            self.returncode = -9

        def wait(self, timeout=None):
            return self.returncode

    monkeypatch.setattr(server.subprocess, "Popen", FakePopen)
    server.dispatch_task_worker(task_id)
    after = _task(task_id)
    assert after["execution_state"] == "succeeded"
    assert after["status"] == "待人工审查"
    assert after["execution_tool"] == "Cursor->Claude Code"
    assert "fallback ok" in (after["execution_output"] or "")


def test_dispatch_worker_build_error_to_unsupported(isolated_env, monkeypatch: pytest.MonkeyPatch):
    task_id = _new_task(assignee_ai="Cursor")
    monkeypatch.setattr(server, "build_tool_run_command", lambda tool, prompt: (None, "不支持"))
    monkeypatch.setattr(server, "pick_fallback_tool", lambda preferred_tools=None: (None, "无回退工具"))

    server.dispatch_task_worker(task_id)
    after = _task(task_id)
    assert after["execution_state"] == "unsupported"
    assert after["status"] == "待分配"
    assert "无回退工具" in (after["execution_error"] or "")


def test_dispatch_worker_timeout_path(isolated_env, monkeypatch: pytest.MonkeyPatch):
    task_id = _new_task()

    monkeypatch.setattr(server, "build_tool_run_command", lambda tool, prompt: (["fake-cli", prompt], None))
    monkeypatch.setattr(server, "get_dispatch_timeout_seconds", lambda: 60)
    monkeypatch.setattr(server.time, "sleep", lambda *_: None)

    ticks = iter([0.0, 61.0, 61.1])
    monkeypatch.setattr(server.time, "monotonic", lambda: next(ticks, 999.0))

    class FakePopen:
        def __init__(self, cmd, cwd, text, encoding, errors, stdout, stderr):
            self.returncode = None
            self.pid = 32345
            stdout.write("long running\n")
            stdout.flush()

        def poll(self):
            return None

        def kill(self):
            self.returncode = -9

        def wait(self, timeout=None):
            return self.returncode

    monkeypatch.setattr(server.subprocess, "Popen", FakePopen)
    server.dispatch_task_worker(task_id)
    after = _task(task_id)
    assert after["execution_state"] == "failed"
    assert "执行超时" in (after["execution_error"] or "")
    assert after["status"] == "AI执行中"

