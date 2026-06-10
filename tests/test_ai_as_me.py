from __future__ import annotations

from pathlib import Path

import pytest

import server


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    data_dir = tmp_path / "data"
    authority_dir = tmp_path / "AI-as-Me"
    authority_dir.mkdir()
    authority = authority_dir / "authority.yaml"
    authority.write_text("mode: shadow\nauto_execute_actions:\n  - dispatch_task\n", encoding="utf-8")
    monkeypatch.setattr(server, "DATA_DIR", data_dir)
    monkeypatch.setattr(server, "DB_PATH", data_dir / "test.db")
    monkeypatch.setattr(server, "AI_AS_ME_DIR", authority_dir)
    monkeypatch.setattr(server, "AUTHORITY_PATH", authority)
    server.init_db()
    with server.app.test_client() as test_client:
        yield test_client, authority


def test_shadow_mode_never_executes_and_records_audit(client):
    test_client, _ = client
    response = test_client.post(
        "/api/ai-as-me/decide",
        json={"intent": "创建任务检查项目风险", "execute": True},
    )
    assert response.status_code == 200
    body = response.get_json()
    assert body["mode"] == "shadow"
    assert body["authority_level"] == "L2"
    assert body["can_execute"] is False
    status = test_client.get("/api/ai-as-me/status").get_json()
    assert status["recent_decisions"][0]["id"] == body["decision_id"]


def test_high_risk_action_never_auto_executes(client):
    test_client, authority = client
    authority.write_text("mode: delegated\nauto_execute_actions:\n  - dispatch_task\n", encoding="utf-8")
    body = test_client.post(
        "/api/ai-as-me/decide",
        json={"intent": "向客户付款并签合同", "execute": True},
    ).get_json()
    assert body["authority_level"] == "L3"
    assert body["risk_level"] == "high"
    assert body["can_execute"] is False
    assert body["requires_approval"] is True


def test_internal_execution_without_adapter_is_advice_only(client):
    test_client, authority = client
    authority.write_text(
        "mode: delegated\nauto_execute_actions:\n  - internal_execution\n",
        encoding="utf-8",
    )
    body = test_client.post(
        "/api/ai-as-me/decide",
        json={"intent": "更新内部项目文档", "execute": True},
    ).get_json()
    assert body["action_type"] == "internal_execution"
    assert body["policy"]["explicitly_allowed"] is True
    assert body["policy"]["executor_available"] is False
    assert body["can_execute"] is False


def test_delegated_dispatch_is_authorized(client, monkeypatch: pytest.MonkeyPatch):
    test_client, authority = client
    authority.write_text(
        "mode: delegated\nauto_execute_actions:\n  - dispatch_task\n",
        encoding="utf-8",
    )

    class FakeThread:
        def __init__(self, target=None, args=None, daemon=None):
            self.args = args

        def start(self):
            return None

    monkeypatch.setattr(server.threading, "Thread", FakeThread)
    body = test_client.post(
        "/api/ai-as-me/decide",
        json={"intent": "创建任务检查项目风险", "execute": True},
    ).get_json()
    assert body["can_execute"] is True
    assert body["execution_status"] == "dispatched"
    assert body["execution"]["task_id"] > 0


def test_feedback_is_persisted(client):
    test_client, authority = client
    decision = test_client.post("/api/ai-as-me/decide", json={"intent": "分析今天项目优先级"}).get_json()
    response = test_client.post(
        "/api/ai-as-me/feedback",
        json={"decision_id": decision["decision_id"], "feedback": "approve", "comment": "符合我的判断"},
    )
    assert response.status_code == 200
    assert response.get_json()["decision"]["feedback"] == "approve"
    assert (authority.parent / "decision-cases" / f"decision-{decision['decision_id']}.md").exists()
