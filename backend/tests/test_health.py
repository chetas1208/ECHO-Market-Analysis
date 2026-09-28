import httpx

from app.core.config import Settings
from app.db.session import close_db, init_db
from app.main import create_app


async def test_health_ok(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
    assert resp.headers["x-request-id"]


async def test_ready_ok(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/v1/ready")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ready", "checks": {"database": "ok"}}


async def test_ready_503_when_database_down() -> None:
    settings = Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://echo:wrong@127.0.0.1:1/echo",
        log_level="WARNING",
    )
    app = create_app(settings, manage_db=False)
    init_db(app, settings)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        ready = await http.get("/api/v1/ready")
        assert ready.status_code == 503
        assert ready.json() == {"status": "not_ready", "checks": {"database": "error"}}

        # liveness does not depend on the database
        assert (await http.get("/api/v1/health")).status_code == 200

        # data endpoints report a database_error envelope, without internals
        resp = await http.get("/api/v1/events")
        assert resp.status_code == 503
        assert resp.json()["error"]["code"] == "database_error"
        assert "Traceback" not in resp.text
        assert "wrong" not in resp.text
    await close_db(app)
