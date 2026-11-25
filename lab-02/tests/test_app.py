import importlib
import sys
from pathlib import Path

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture
def app_module(tmp_path, monkeypatch):
    monkeypatch.setenv("COUNTER_FILE", str(tmp_path / "data" / "visits.txt"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("PARTNER_URL", "http://partner.invalid")
    import app as app_module

    importlib.reload(app_module)
    app_module.app.config["TESTING"] = True
    return app_module


@pytest.fixture
def client(app_module):
    return app_module.app.test_client()


def test_health_is_exactly_ok(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.get_data(as_text=True) == "ok\n"


def test_health_ignores_the_database(app_module, client, monkeypatch):
    monkeypatch.setattr(app_module, "DATABASE_URL", "postgresql://nope")
    monkeypatch.setattr(app_module, "_db", lambda: (_ for _ in ()).throw(RuntimeError("db down")))
    assert client.get("/health").status_code == 200


def test_ready_with_file_store(app_module, client):
    r = client.get("/ready")
    assert r.status_code == 200
    body = r.get_json()
    assert body["ready"] is True
    assert body["store"] == f"file:{app_module.COUNTER_FILE}"
    assert app_module.COUNTER_FILE.parent.is_dir()


def test_ready_503_when_database_unreachable(app_module, client, monkeypatch):
    monkeypatch.setattr(app_module, "DATABASE_URL", "postgresql://nope")

    def boom():
        raise RuntimeError("connection refused")

    monkeypatch.setattr(app_module, "_db", boom)
    r = client.get("/ready")
    assert r.status_code == 503
    body = r.get_json()
    assert body["ready"] is False
    assert "connection refused" in body["error"]


def test_ready_503_when_data_dir_is_not_a_directory(app_module, client, tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("a file where a directory should be")
    app_module.COUNTER_FILE = blocker / "visits.txt"
    r = client.get("/ready")
    assert r.status_code == 503
    assert r.get_json()["ready"] is False


def test_visits_counts_up_from_one(client):
    seen = [client.get("/visits").get_json()["visits"] for _ in range(3)]
    assert seen == [1, 2, 3]


def test_visits_reports_file_store(client):
    assert client.get("/visits").get_json()["store"] == "file"


def test_visits_persists_to_the_file(app_module, client):
    client.get("/visits")
    client.get("/visits")
    assert app_module.COUNTER_FILE.read_text() == "2"


def test_visits_resumes_from_existing_state(app_module, client):
    app_module.COUNTER_FILE.parent.mkdir(parents=True)
    app_module.COUNTER_FILE.write_text("41")
    assert client.get("/visits").get_json()["visits"] == 42


def test_visits_tolerates_empty_file(app_module, client):
    app_module.COUNTER_FILE.parent.mkdir(parents=True)
    app_module.COUNTER_FILE.write_text("")
    assert client.get("/visits").get_json()["visits"] == 1


def test_visits_503_when_storage_fails(app_module, client, tmp_path):
    app_module.COUNTER_FILE = tmp_path  # a directory: read/write must fail
    r = client.get("/visits")
    assert r.status_code == 503
    body = r.get_json()
    assert "error" in body and body["store"] == "file"


def test_visits_uses_postgres_when_configured(app_module, client, monkeypatch):
    monkeypatch.setattr(app_module, "DATABASE_URL", "postgresql://fake")
    monkeypatch.setattr(app_module, "bump_db", lambda: 7)
    body = client.get("/visits").get_json()
    assert body == {"visits": 7, "store": "postgres"}


class FakeResponse:
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self._payload = payload or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error")

    def json(self):
        return self._payload


def test_price_relays_partner_answer(app_module, client, monkeypatch):
    calls = []

    def fake_get(url, timeout):
        calls.append((url, timeout))
        return FakeResponse(payload={"sku": "MK-II", "price": "1234.56", "currency": "UAH"})

    monkeypatch.setattr(app_module.requests, "get", fake_get)
    r = client.get("/price/MK-II")
    assert r.status_code == 200
    body = r.get_json()
    assert body["sku"] == "MK-II"
    assert body["price"] == "1234.56"
    assert body["currency"] == "UAH"
    assert calls[0][0] == "http://partner.invalid/v1/catalog/MK-II"
    assert calls[0][1] == app_module.PARTNER_TIMEOUT


def test_price_502_when_partner_errors(app_module, client, monkeypatch):
    monkeypatch.setattr(app_module.requests, "get", lambda url, timeout: FakeResponse(status=500))
    r = client.get("/price/MK-II")
    assert r.status_code == 502
    assert r.get_json()["error"] == "HTTPError"


def test_price_502_when_partner_times_out(app_module, client, monkeypatch):
    def timeout(url, timeout):
        raise requests.Timeout("too slow")

    monkeypatch.setattr(app_module.requests, "get", timeout)
    r = client.get("/price/MK-II")
    assert r.status_code == 502
    assert r.get_json()["error"] == "Timeout"


def test_price_fails_loudly_when_the_partner_is_unreachable(app_module, monkeypatch):
    """No fake at all: point the app at a closed local port and let the real request fail."""
    monkeypatch.setattr(app_module, "PARTNER_URL", "http://127.0.0.1:9")
    monkeypatch.setattr(app_module, "PARTNER_TIMEOUT", 0.25)
    r = app_module.app.test_client().get("/price/MK-II")
    assert r.status_code == 502
    body = r.get_json()
    assert body["sku"] == "MK-II"
    assert "127.0.0.1:9" in body["source"]
    assert body["error"] in {"ConnectionError", "Timeout", "ConnectTimeout"}
