"""Day 11 observability contracts."""

import httpx

from app.observability.metrics import MetricsRegistry


def test_metrics_registry_renders_prometheus_histogram_and_escaped_labels() -> None:
    registry = MetricsRegistry()
    registry.inc("echo_test_total", labels={"path": '/a"b'})
    registry.observe("echo_test_duration_seconds", 0.02, labels={"route": "/health"})

    body = registry.render()

    assert 'echo_test_total{path="/a\\"b"} 1' in body
    assert 'echo_test_duration_seconds_bucket{route="/health",le="0.025"} 1' in body
    assert "echo_test_duration_seconds_count{route=\"/health\"} 1" in body


async def test_metrics_endpoint_and_trace_header(client: httpx.AsyncClient) -> None:
    await client.get("/api/v1/health")
    response = await client.get(
        "/metrics",
        headers={"X-Request-ID": "ops-request-1", "X-Trace-ID": "ops-trace-1"},
    )

    assert response.status_code == 200
    assert response.headers["x-request-id"] == "ops-request-1"
    assert response.headers["x-trace-id"] == "ops-trace-1"
    assert "echo_http_requests_total" in response.text
    assert "echo_build_info" in response.text


async def test_operational_status_preserves_liveness_when_database_is_down() -> None:
    from app.core.config import Settings
    from app.db.session import close_db, init_db
    from app.main import create_app

    settings = Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://echo:wrong@127.0.0.1:1/echo",
        log_level="WARNING",
    )
    app = create_app(settings, manage_db=False)
    init_db(app, settings)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
            response = await http.get("/api/v1/ops/status")
        assert response.status_code == 200
        payload = response.json()
        assert payload["liveness"] == "ok"
        assert payload["status"] == "UNAVAILABLE"
        assert payload["dependencies"]["database"]["state"] == "UNAVAILABLE"
    finally:
        await close_db(app)
