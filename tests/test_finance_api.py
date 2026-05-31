from __future__ import annotations

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
    monkeypatch.setattr(server, "resolve_company_dir", lambda: (company_dir, "safe_home_company"))
    monkeypatch.setattr(server, "PM_SCRIPT", tmp_path / "pm")

    server.init_db()
    with server.app.test_client() as test_client:
        yield test_client


def test_overview_empty_when_no_data(client):
    resp = client.get("/api/finance/overview")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["has_data"] is False
    assert body["transaction_count"] == 0
    assert body["cash_balance_cents"] == 0
    assert body["runway_months"] is None


def test_transaction_roundtrip_and_overview_aggregation(client):
    import datetime

    today_month = datetime.date.today().strftime("%Y-%m")
    incomes = [
        {"occurred_on": f"{today_month}-05", "amount": "5000", "direction": "in", "category": "服务收入"},
        {"occurred_on": f"{today_month}-12", "amount": "8000.50", "direction": "in", "category": "咨询费"},
    ]
    expenses = [
        {"occurred_on": f"{today_month}-03", "amount": "1200", "direction": "out", "category": "服务器", "vendor": "Vercel"},
        {"occurred_on": f"{today_month}-20", "amount": "299", "direction": "out", "category": "订阅", "vendor": "OpenAI"},
    ]
    for tx in incomes + expenses:
        r = client.post("/api/finance/transactions", json=tx)
        assert r.status_code == 201, r.get_data(as_text=True)

    listed = client.get("/api/finance/transactions").get_json()
    assert len(listed) == 4
    assert all("amount_label" in t for t in listed)

    filt = client.get("/api/finance/transactions?direction=in").get_json()
    assert len(filt) == 2

    overview = client.get("/api/finance/overview").get_json()
    assert overview["has_data"] is True
    assert overview["current_month_income_cents"] == 1_300_050  # 5000 + 8000.50 in cents
    assert overview["current_month_expense_cents"] == 149_900  # 1200 + 299
    assert overview["cash_balance_cents"] == 1_300_050 - 149_900
    assert overview["currency"] == "CNY"
    assert overview["labels"]["current_month_income"].startswith("13,000.50")


def test_transaction_validation_rejects_bad_input(client):
    bad_date = client.post(
        "/api/finance/transactions",
        json={"occurred_on": "2026/05/24", "amount": "100", "direction": "in"},
    )
    assert bad_date.status_code == 400
    bad_amount = client.post(
        "/api/finance/transactions",
        json={"occurred_on": "2026-05-24", "amount": "abc", "direction": "in"},
    )
    assert bad_amount.status_code == 400
    bad_dir = client.post(
        "/api/finance/transactions",
        json={"occurred_on": "2026-05-24", "amount": "100", "direction": "credit"},
    )
    assert bad_dir.status_code == 400


def test_transaction_delete(client):
    created = client.post(
        "/api/finance/transactions",
        json={"occurred_on": "2026-05-24", "amount": "50", "direction": "out"},
    ).get_json()
    tid = created["id"]
    assert client.delete(f"/api/finance/transactions/{tid}").status_code == 200
    assert client.delete(f"/api/finance/transactions/{tid}").status_code == 404


def test_subscription_crud_and_monthly_equivalent(client):
    # 季付 600 → monthly equiv 200
    created = client.post(
        "/api/finance/subscriptions",
        json={"name": "GitHub Copilot 团队版", "amount": "600", "cycle": "quarterly", "vendor": "GitHub"},
    )
    assert created.status_code == 201
    body = created.get_json()
    assert body["monthly_equivalent_cents"] == 20_000  # 600/3 * 100

    listed = client.get("/api/finance/subscriptions").get_json()
    assert len(listed) == 1
    assert listed[0]["cycle"] == "quarterly"

    patched = client.patch(
        f"/api/finance/subscriptions/{body['id']}",
        json={"status": "paused", "amount": "900"},
    )
    assert patched.status_code == 200
    assert patched.get_json()["status"] == "paused"
    assert patched.get_json()["amount_cents"] == 90_000

    # active 筛选不应包含 paused 的订阅
    active_only = client.get("/api/finance/subscriptions?status=active").get_json()
    assert active_only == []

    assert client.delete(f"/api/finance/subscriptions/{body['id']}").status_code == 200
    assert client.delete(f"/api/finance/subscriptions/{body['id']}").status_code == 404


def test_subscription_overview_adds_to_monthly_burn(client):
    client.post(
        "/api/finance/subscriptions",
        json={"name": "Vercel Pro", "amount": "200", "cycle": "monthly"},
    )
    client.post(
        "/api/finance/subscriptions",
        json={"name": "Domain renewal", "amount": "120", "cycle": "yearly"},
    )
    overview = client.get("/api/finance/overview").get_json()
    # 200 monthly + 120/12 monthly = 200 + 10 = 210 RMB = 21000 cents
    assert overview["subscription_monthly_cents"] == 21_000
    assert overview["subscription_count"] == 2


def test_csv_import_happy_path(client):
    csv_body = (
        "date,amount,direction,category,vendor,note\n"
        "2026-05-01,3000,in,服务收入,客户A,首期款\n"
        "2026-05-03,150.50,out,差旅,滴滴,机场\n"
        "2026-05-10,bad,out,异常,,\n"
    )
    resp = client.post(
        "/api/finance/transactions/import-csv",
        data=csv_body,
        content_type="text/csv",
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["imported"] == 2
    assert len(body["skipped"]) == 1
    assert body["skipped"][0]["row"] == 4

    listed = client.get("/api/finance/transactions").get_json()
    assert len(listed) == 2
    sources = {t["source"] for t in listed}
    assert sources == {"csv"}


def test_csv_import_rejects_missing_columns(client):
    resp = client.post(
        "/api/finance/transactions/import-csv",
        data="foo,bar\n1,2\n",
        content_type="text/csv",
    )
    assert resp.status_code == 400
    assert "missing required columns" in resp.get_json()["error"]


def test_csv_import_rejects_empty_body(client):
    resp = client.post(
        "/api/finance/transactions/import-csv", data="", content_type="text/csv"
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# OCR endpoint
# ---------------------------------------------------------------------------

import io as _io
import json as _json

from src import finance as _finance_module


def _fake_gemini_response(json_payload: dict) -> object:
    """Return an object whose .read() returns a Gemini API JSON envelope."""

    class _Resp:
        def __init__(self, body: bytes):
            self._body = body

        def read(self) -> bytes:
            return self._body

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    envelope = {
        "candidates": [
            {"content": {"parts": [{"text": _json.dumps(json_payload, ensure_ascii=False)}]}}
        ]
    }
    return _Resp(_json.dumps(envelope).encode("utf-8"))


def test_ocr_status_reflects_env(client, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("CEO_CONSOLE_GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    assert client.get("/api/finance/ocr/status").get_json() == {"configured": False}
    monkeypatch.setenv("CEO_CONSOLE_GEMINI_API_KEY", "test-key")
    assert client.get("/api/finance/ocr/status").get_json() == {"configured": True}


def test_ocr_requires_api_key(client, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("CEO_CONSOLE_GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    resp = client.post(
        "/api/finance/ocr",
        data={"file": (_io.BytesIO(b"\xff\xd8\xff fake jpg"), "test.jpg", "image/jpeg")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 503
    assert "Gemini API key" in resp.get_json()["error"]


def test_ocr_rejects_empty_and_unsupported(client, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CEO_CONSOLE_GEMINI_API_KEY", "test-key")
    # missing file field
    missing = client.post("/api/finance/ocr", data={}, content_type="multipart/form-data")
    assert missing.status_code == 400
    # unsupported mime
    unsupported = client.post(
        "/api/finance/ocr",
        data={"file": (_io.BytesIO(b"plain"), "note.txt", "text/plain")},
        content_type="multipart/form-data",
    )
    assert unsupported.status_code == 415


def test_ocr_happy_path_returns_extracted_fields(
    client, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    monkeypatch.setenv("CEO_CONSOLE_GEMINI_API_KEY", "test-key")
    # Receipts dir lives under server.DATA_DIR (which the fixture pointed at tmp_path).
    monkeypatch.setattr(
        _finance_module, "RECEIPTS_DIR", server.DATA_DIR / "finance" / "receipts"
    )

    captured: dict = {}

    def fake_urlopen(req, timeout=60):
        captured["url"] = req.full_url
        captured["body_len"] = len(req.data)
        return _fake_gemini_response(
            {
                "occurred_on": "2026-05-24",
                "amount": "1,288.50",
                "direction": "out",
                "vendor": "京东",
                "category": "办公用品",
                "currency": "CNY",
                "note": "笔记本 + 鼠标",
                "confidence": 0.92,
            }
        )

    monkeypatch.setattr(_finance_module.urllib.request, "urlopen", fake_urlopen)

    fake_image = b"\xff\xd8\xff\xe0fake-jpeg-bytes"
    resp = client.post(
        "/api/finance/ocr",
        data={"file": (_io.BytesIO(fake_image), "receipt.jpg", "image/jpeg")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()
    extracted = body["extracted"]
    assert extracted["occurred_on"] == "2026-05-24"
    assert extracted["amount"] == "1288.50"
    assert extracted["direction"] == "out"
    assert extracted["vendor"] == "京东"
    assert extracted["currency"] == "CNY"
    assert 0.0 <= extracted["confidence"] <= 1.0
    assert body["receipt_url"].startswith("/api/finance/receipts/")

    # Image actually persisted
    receipt_name = body["receipt_filename"]
    on_disk = server.DATA_DIR / "finance" / "receipts" / receipt_name
    assert on_disk.exists()
    assert on_disk.read_bytes() == fake_image

    # And served back via the receipts endpoint
    download = client.get(body["receipt_url"])
    assert download.status_code == 200
    assert download.data == fake_image


def test_ocr_handles_gemini_error(client, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CEO_CONSOLE_GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(
        _finance_module, "RECEIPTS_DIR", server.DATA_DIR / "finance" / "receipts"
    )

    def boom(req, timeout=60):
        raise RuntimeError("network down")

    monkeypatch.setattr(_finance_module.urllib.request, "urlopen", boom)
    resp = client.post(
        "/api/finance/ocr",
        data={"file": (_io.BytesIO(b"\xff\xd8\xff"), "x.jpg", "image/jpeg")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 502
    assert "Gemini request failed" in resp.get_json()["error"]


def test_ocr_extracted_parser_handles_garbage(monkeypatch: pytest.MonkeyPatch):
    # Even if the model returns prose with embedded JSON, we should salvage it.
    raw = "对，识别结果是：\n{\"occurred_on\":\"2026-05-01\",\"amount\":\"99.9\",\"direction\":\"in\",\"vendor\":\"A\"}\n谢谢"
    parsed = _finance_module.parse_ocr_extracted(raw)
    assert parsed["occurred_on"] == "2026-05-01"
    assert parsed["amount"] == "99.90"
    assert parsed["direction"] == "in"
    assert parsed["vendor"] == "A"

    # Totally non-JSON returns safe defaults.
    blank = _finance_module.parse_ocr_extracted("not json at all")
    assert blank["amount"] == ""
    assert blank["direction"] == "out"


def test_receipt_endpoint_blocks_path_traversal(client):
    resp = client.get("/api/finance/receipts/..%2F..%2Fceo_console.db")
    assert resp.status_code == 404
