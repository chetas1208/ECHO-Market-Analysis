"""Typed market configuration.

Secrets and environment-specific values come from env vars (ECHO_MARKET_*, MASSIVE_API_KEY,
ALPACA_API_KEY/ALPACA_API_SECRET). Non-secret strategy defaults live here as typed defaults.
Missing credentials must NEVER block startup (provider state -> UNCONFIGURED).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, BaseModel, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.config import ROOT_ENV_FILE

UNIVERSE_PATH = Path(__file__).resolve().parents[2] / "config" / "universe.yaml"


class ShockWeights(BaseModel):
    """Initial heuristic weights (documented starting point, NOT empirically optimized)."""

    ret: float = 0.30
    volume: float = 0.20
    volatility: float = 0.20
    sector: float = 0.20
    market: float = 0.10

    @model_validator(mode="after")
    def _weights_valid(self) -> ShockWeights:
        vals = [self.ret, self.volume, self.volatility, self.sector, self.market]
        if any(v < 0 for v in vals):
            raise ValueError("shock weights must be non-negative")
        if abs(sum(vals) - 1.0) > 1e-6:
            raise ValueError(f"shock weights must sum to 1.0 (got {sum(vals):.6f})")
        return self


class ShockConfig(BaseModel):
    weights: ShockWeights = Field(default_factory=ShockWeights)
    z_cap: float = 6.0  # component f(z)=min(|z|/z_cap,1): clamps pathological values
    watch_threshold: float = 0.35
    shock_threshold: float = 0.55
    severe_threshold: float = 0.75
    cooldown_seconds: int = 900  # same symbol+direction suppressed unless level escalates

    @model_validator(mode="after")
    def _thresholds_increasing(self) -> ShockConfig:
        if not (0.0 < self.watch_threshold < self.shock_threshold < self.severe_threshold):
            raise ValueError("thresholds must satisfy 0 < watch < shock < severe")
        return self


class FeatureConfig(BaseModel):
    baseline_bars: int = 390  # rolling baseline window (1m bars)
    min_baseline_bars: int = 60  # below -> WARMING_UP
    beta_window_bars: int = 390
    min_beta_bars: int = 60
    vol_window_bars: int = 15  # realized vol window
    tod_bucket_minutes: int = 5  # time-of-day bucket for volume seasonality
    tod_min_days: int = 5  # min prior sessions per bucket to use "tod" method
    # per-symbol in-memory 1m cap: 7 sessions x 390; must exceed tod_min_days x 390
    history_bars: int = 2730


class ReconnectConfig(BaseModel):
    base_delay_s: float = 1.0
    max_delay_s: float = 60.0
    factor: float = 2.0
    jitter: float = 0.3  # +/- fraction
    stale_after_s: float = 90.0  # no message while market active -> STALE


class MarketSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        populate_by_name=True,
    )

    echo_mode: Literal["live", "replay", "offline"] = "offline"
    echo_market_provider: Literal["off", "replay", "massive", "alpaca"] = "off"
    echo_market_fallback: Literal["none", "alpaca"] = "none"
    echo_market_queue_size: int = 5000
    echo_market_replay_speed: float = 0.0  # 0 = as fast as possible; 1.0 = real time

    # Secrets: consumers must call `.get_secret_value()` (never logged/repr'd/dumped).
    massive_api_key: SecretStr | None = None
    alpaca_api_key: SecretStr | None = None
    alpaca_api_secret: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("ALPACA_API_SECRET", "ALPACA_SECRET_KEY"),
    )
    alpaca_feed: Literal["iex", "sip"] = "iex"

    features: FeatureConfig = Field(default_factory=FeatureConfig)
    shock: ShockConfig = Field(default_factory=ShockConfig)
    reconnect: ReconnectConfig = Field(default_factory=ReconnectConfig)

    @field_validator("echo_market_queue_size")
    @classmethod
    def _queue_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("echo_market_queue_size must be > 0")
        return v

    @model_validator(mode="after")
    def _live_provider_requires_credentials(self) -> MarketSettings:
        if (
            self.echo_mode == "live"
            and self.echo_market_provider == "massive"
            and not self.massive_configured
        ):
            raise ValueError("live Massive mode requires MASSIVE_API_KEY")
        if (
            self.echo_mode == "live"
            and self.echo_market_provider == "alpaca"
            and not self.alpaca_configured
        ):
            raise ValueError("live Alpaca mode requires ALPACA_API_KEY and ALPACA_API_SECRET")
        return self

    @staticmethod
    def _has(secret: SecretStr | None) -> bool:
        return secret is not None and bool(secret.get_secret_value().strip())

    @property
    def massive_configured(self) -> bool:
        return self._has(self.massive_api_key)

    @property
    def alpaca_configured(self) -> bool:
        return self._has(self.alpaca_api_key) and self._has(self.alpaca_api_secret)


@lru_cache
def get_market_settings() -> MarketSettings:
    return MarketSettings()
