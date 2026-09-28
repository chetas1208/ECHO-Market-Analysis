"""Configuration, fallback, and secret-safety contracts for the environment bootstrap."""

from pathlib import Path

import httpx
import pytest

from app.core.config import Settings
from app.execution.settings import ExecutionSettings
from app.graph.backend import resolve_graph_backend
from app.main import create_app
from app.market.settings import MarketSettings


def test_aure_unavailable_uses_explicit_networkx_fallback(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        graph_backend="aure",
        graph_fallback_backend="networkx",
        aure_enabled=True,
        aure_binary=tmp_path / "missing-aure",
        aure_database_path=tmp_path / "missing.auredb",
    )
    status = resolve_graph_backend(settings)
    assert status.active == "networkx"
    assert status.state == "FALLBACK"
    assert "does not exist" in status.reason or "not on PATH" in status.reason


def test_paper_mode_rejects_false_paper_flag() -> None:
    with pytest.raises(ValueError, match="paper execution"):
        ExecutionSettings(_env_file=None, execution_mode="PAPER", alpaca_paper=False)


def test_live_massive_mode_requires_a_credential() -> None:
    with pytest.raises(ValueError, match="MASSIVE_API_KEY"):
        MarketSettings(
            _env_file=None,
            echo_mode="live",
            echo_market_provider="massive",
        )


def test_env_example_contains_no_live_secret_values() -> None:
    example = (Path(__file__).resolve().parents[2] / ".env.example").read_text()
    assert "MASSIVE_API_KEY=" in example
    assert "WORLD_MONITOR_API_KEY=" in example
    assert "ALPACA_API_SECRET=" in example
    assert "wm_" not in example
    assert "sk-" not in example


async def test_config_status_never_exposes_provider_secret(
    test_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    massive_secret = "massive-test-secret"
    world_secret = "wm_test_secret_value"
    monkeypatch.setenv("MASSIVE_API_KEY", massive_secret)
    monkeypatch.setenv("WORLD_MONITOR_API_KEY", world_secret)
    app = create_app(test_settings, manage_db=False)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/system/config-status")
    assert response.status_code == 200
    body = response.text
    assert massive_secret not in body
    assert world_secret not in body
    assert "database_url" not in body
