"""MarketSettings: defaults, env overrides, validators, secret hygiene. No network/creds."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.market.settings import (
    MarketSettings,
    ShockConfig,
    ShockWeights,
    get_market_settings,
)

_ENV_KEYS = [
    "ECHO_MARKET_PROVIDER",
    "ECHO_MARKET_FALLBACK",
    "ECHO_MARKET_QUEUE_SIZE",
    "ECHO_MARKET_REPLAY_SPEED",
    "MASSIVE_API_KEY",
    "ALPACA_API_KEY",
    "ALPACA_API_SECRET",
    "ALPACA_FEED",
]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch):
    for k in _ENV_KEYS:
        monkeypatch.delenv(k, raising=False)
    get_market_settings.cache_clear()
    yield
    get_market_settings.cache_clear()


def _fresh() -> MarketSettings:
    # _env_file=None: ignore any developer .env so tests are hermetic
    return MarketSettings(_env_file=None)


def test_defaults_provider_off_no_creds():
    s = _fresh()
    assert s.echo_market_provider == "off"
    assert s.echo_market_fallback == "none"
    assert s.echo_market_queue_size == 5000
    assert s.echo_market_replay_speed == 0.0
    assert s.alpaca_feed == "iex"
    assert s.massive_api_key is None and s.alpaca_api_key is None
    assert not s.massive_configured and not s.alpaca_configured


def test_env_override_provider_replay(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ECHO_MARKET_PROVIDER", "replay")
    monkeypatch.setenv("ECHO_MARKET_QUEUE_SIZE", "123")
    monkeypatch.setenv("ECHO_MARKET_REPLAY_SPEED", "2.5")
    get_market_settings.cache_clear()
    s = get_market_settings()
    assert s.echo_market_provider == "replay"
    assert s.echo_market_queue_size == 123
    assert s.echo_market_replay_speed == 2.5
    assert get_market_settings() is s  # cached


def test_invalid_provider_rejected(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ECHO_MARKET_PROVIDER", "bogus")
    with pytest.raises(ValidationError):
        _fresh()


def test_invalid_fallback_and_feed_rejected(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ECHO_MARKET_FALLBACK", "massive")
    with pytest.raises(ValidationError):
        _fresh()
    monkeypatch.delenv("ECHO_MARKET_FALLBACK")
    monkeypatch.setenv("ALPACA_FEED", "otc")
    with pytest.raises(ValidationError):
        _fresh()


def test_massive_configured(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MASSIVE_API_KEY", "k-123")
    s = _fresh()
    assert s.massive_configured and not s.alpaca_configured
    assert s.massive_api_key is not None and s.massive_api_key.get_secret_value() == "k-123"


def test_empty_or_blank_secret_not_configured(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MASSIVE_API_KEY", "")
    monkeypatch.setenv("ALPACA_API_KEY", "  ")
    monkeypatch.setenv("ALPACA_API_SECRET", "s")
    s = _fresh()
    assert not s.massive_configured
    assert not s.alpaca_configured


def test_alpaca_needs_key_and_secret(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ALPACA_API_KEY", "ak")
    assert not _fresh().alpaca_configured
    monkeypatch.delenv("ALPACA_API_KEY")
    monkeypatch.setenv("ALPACA_API_SECRET", "as")
    assert not _fresh().alpaca_configured
    monkeypatch.setenv("ALPACA_API_KEY", "ak")
    assert _fresh().alpaca_configured


def test_secrets_never_in_repr_or_dump(monkeypatch: pytest.MonkeyPatch):
    secrets = {
        "MASSIVE_API_KEY": "sekret-m",
        "ALPACA_API_KEY": "sekret-a",
        "ALPACA_API_SECRET": "sekret-s",
    }
    for k, v in secrets.items():
        monkeypatch.setenv(k, v)
    s = _fresh()
    blobs = [repr(s), str(s), repr(s.model_dump()), s.model_dump_json()]
    for blob in blobs:
        for v in secrets.values():
            assert v not in blob


def test_nested_defaults_sane():
    s = _fresh()
    w = s.shock.weights
    assert sum([w.ret, w.volume, w.volatility, w.sector, w.market]) == pytest.approx(1.0)
    sh = s.shock
    assert 0 < sh.watch_threshold < sh.shock_threshold < sh.severe_threshold <= 1.0
    assert s.features.min_baseline_bars <= s.features.baseline_bars
    assert s.reconnect.base_delay_s <= s.reconnect.max_delay_s


def test_weights_must_sum_to_one():
    with pytest.raises(ValidationError):
        ShockWeights(ret=0.5)  # sum 1.2
    with pytest.raises(ValidationError):
        ShockWeights(ret=-0.1, volume=0.4)  # negative
    ShockWeights(ret=0.2, volume=0.2, volatility=0.2, sector=0.2, market=0.2)


@pytest.mark.parametrize(
    ("watch", "shock", "severe"),
    [(0.55, 0.55, 0.75), (0.6, 0.55, 0.75), (0.35, 0.8, 0.75), (0.0, 0.5, 0.7), (-0.1, 0.5, 0.7)],
)
def test_thresholds_must_strictly_increase(watch: float, shock: float, severe: float):
    with pytest.raises(ValidationError):
        ShockConfig(watch_threshold=watch, shock_threshold=shock, severe_threshold=severe)


@pytest.mark.parametrize("bad", [0, -1])
def test_queue_size_must_be_positive(bad: int, monkeypatch: pytest.MonkeyPatch):
    with pytest.raises(ValidationError):
        MarketSettings(_env_file=None, echo_market_queue_size=bad)
    monkeypatch.setenv("ECHO_MARKET_QUEUE_SIZE", str(bad))
    with pytest.raises(ValidationError):
        _fresh()
