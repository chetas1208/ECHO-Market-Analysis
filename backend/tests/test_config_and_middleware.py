import io
import json
import logging
from collections.abc import Iterator

import httpx
import pytest

from app.core.config import Settings
from app.core.logging import JsonFormatter
from app.main import create_app


def test_settings_defaults_boot_without_any_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("DATABASE_URL", "CORS_ALLOW_ORIGINS", "API_PORT", "LOG_LEVEL", "APP_ENV"):
        monkeypatch.delenv(name, raising=False)
    settings = Settings(_env_file=None)
    assert settings.database_url.startswith("postgresql+asyncpg://")
    assert settings.api_port == 8100
    assert settings.cors_allow_origins == ["http://localhost:3000", "http://127.0.0.1:3000"]


def test_settings_from_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@db.example:5432/x")
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "https://a.example, https://b.example/")
    monkeypatch.setenv("LOG_LEVEL", "debug")
    monkeypatch.setenv("MASSIVE_API_KEY", "ignored-future-setting")
    settings = Settings(_env_file=None)
    assert settings.database_url == "postgresql+asyncpg://u:p@db.example:5432/x"
    assert settings.cors_allow_origins == ["https://a.example", "https://b.example"]
    assert settings.log_level == "DEBUG"


def test_settings_reject_wildcard_cors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "*")
    with pytest.raises(ValueError, match="explicit origins"):
        Settings(_env_file=None)


async def test_cors_allows_configured_origin_only(client: httpx.AsyncClient) -> None:
    ok = await client.get("/api/v1/health", headers={"Origin": "http://localhost:3000"})
    assert ok.headers["access-control-allow-origin"] == "http://localhost:3000"
    other = await client.get("/api/v1/health", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in other.headers

    preflight = await client.options(
        "/api/v1/events",
        headers={
            "Origin": "http://127.0.0.1:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == "http://127.0.0.1:3000"


async def test_request_id_generated_and_propagated(client: httpx.AsyncClient) -> None:
    generated = await client.get("/api/v1/health")
    assert len(generated.headers["x-request-id"]) == 32

    resp = await client.get("/api/v1/events/evt_missing", headers={"X-Request-ID": "trace-abc.123"})
    assert resp.headers["x-request-id"] == "trace-abc.123"
    assert resp.json()["error"]["request_id"] == "trace-abc.123"


async def test_malicious_request_id_is_replaced(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/v1/health", headers={"X-Request-ID": "bad id with spaces"})
    assert resp.headers["x-request-id"] != "bad id with spaces"


async def test_unknown_route_uses_error_envelope(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/v1/nope")
    assert resp.status_code == 404
    error = resp.json()["error"]
    assert error["code"] == "not_found"
    assert error["request_id"] == resp.headers["x-request-id"]


async def test_unhandled_exception_returns_500_envelope_without_stack_trace(
    test_settings: Settings,
) -> None:
    app = create_app(test_settings, manage_db=False)

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("secret internal detail")

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        resp = await http.get("/boom", headers={"X-Request-ID": "rid-500"})
    assert resp.status_code == 500
    body = resp.json()
    assert body["error"]["code"] == "internal_error"
    assert body["error"]["request_id"] == "rid-500"
    assert resp.headers["x-request-id"] == "rid-500"
    assert "secret internal detail" not in resp.text
    assert "Traceback" not in resp.text


@pytest.fixture
def json_log_stream() -> Iterator[io.StringIO]:
    """Capture what the app's JSON formatter emits (independent of pytest's stdout capture)."""
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter("echo-api"))
    root = logging.getLogger()
    root.addHandler(handler)
    previous = root.level
    root.setLevel(logging.INFO)
    yield stream
    root.removeHandler(handler)
    root.setLevel(previous)


def _entries(stream: io.StringIO) -> list[dict]:
    return [json.loads(line) for line in stream.getvalue().splitlines() if line.startswith("{")]


async def test_logs_are_json_with_request_id(
    client: httpx.AsyncClient, json_log_stream: io.StringIO
) -> None:
    resp = await client.get("/api/v1/health", headers={"X-Request-ID": "log-check-1"})
    assert resp.status_code == 200
    access = [e for e in _entries(json_log_stream) if e.get("request_id") == "log-check-1"]
    assert access
    entry = access[0]
    assert {"timestamp", "level", "service", "request_id", "operation"} <= set(entry)
    assert entry["path"] == "/api/v1/health" and entry["status_code"] == 200


async def test_event_logging_has_event_id_and_does_not_leak_payload(
    client: httpx.AsyncClient, json_log_stream: io.StringIO
) -> None:
    resp = await client.post(
        "/api/v1/events",
        json={
            "id": "evt_log_test_1",
            "timestamp": "2026-09-20T17:00:00Z",
            "source_type": "world",
            "event_type": "x",
            "title": "t",
            "summary": "PRIVATE-SUMMARY-TEXT",
            "severity": 0.1,
            "novelty": 0.1,
            "confidence": 0.1,
        },
    )
    assert resp.status_code == 201
    entries = _entries(json_log_stream)
    created = [e for e in entries if e.get("operation") == "events.create"]
    assert created and created[0]["event_id"] == "evt_log_test_1"
    assert created[0]["request_id"] == resp.headers["x-request-id"]
    assert "PRIVATE-SUMMARY-TEXT" not in json_log_stream.getvalue()
