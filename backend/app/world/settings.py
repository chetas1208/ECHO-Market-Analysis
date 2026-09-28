"""World-event configuration. Secrets from env; heuristic defaults are typed and documented.
Missing credentials must NEVER block startup (state UNCONFIGURED)."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, BaseModel, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.config import ROOT_ENV_FILE


class SeverityConfig(BaseModel):
    """severity = clamp(class_base * (1 + sum(bonuses)))  -- see scoring/severity.py."""

    geo_scope_bonus: float = 0.10  # multi-country / chokepoint
    infrastructure_bonus: float = 0.15  # known critical infrastructure/chokepoint
    magnitude_bonus: float = 0.15  # source-reported magnitude above class threshold
    provider_importance_weight: float = 0.10  # blend of provider-supplied importance


class CorroborationConfig(BaseModel):
    """corroboration = 1 - exp(-k * effective_independent_sources) blended with diversity."""

    k: float = 0.7
    diversity_weight: float = 0.25
    syndicated_weight: float = 0.15  # a syndicated copy counts as this fraction of a source


class NoveltyConfig(BaseModel):
    lookback_hours: float = 72.0
    entity_weight: float = 0.35
    location_weight: float = 0.25
    class_weight: float = 0.20
    text_weight: float = 0.20
    time_decay_hours: float = 24.0


class DedupConfig(BaseModel):
    time_bucket_hours: float = 6.0
    text_similarity_threshold: float = 0.55  # token-set Jaccard/containment for same-event merge
    max_merge_window_hours: float = 36.0


class WorldSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        populate_by_name=True,
    )

    echo_world_provider: Literal["off", "replay", "world_monitor"] = Field(
        default="off", validation_alias=AliasChoices("ECHO_WORLD_PROVIDER", "WORLD_PROVIDER")
    )
    echo_world_poll_interval_s: float = 1800.0  # WM quota is small; keep polls sparse
    echo_world_replay_speed: float = 0.0
    echo_world_text_model: Literal["off", "modernfinbert"] = "off"
    world_monitor_api_key: SecretStr | None = None
    world_monitor_base_url: str = "https://api.worldmonitor.app"  # verify in references/REPOS.md
    world_monitor_transport: Literal["rest", "mcp"] = Field(
        default="rest",
        validation_alias=AliasChoices("WORLD_MONITOR_TRANSPORT", "WORLDMONITOR_MCP_TRANSPORT"),
    )
    world_monitor_mcp_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices("WORLD_MONITOR_MCP_ENABLED", "WORLDMONITOR_MCP_ENABLED"),
    )
    world_monitor_mcp_url: str = Field(
        default="https://worldmonitor.app/mcp",
        validation_alias=AliasChoices("WORLD_MONITOR_MCP_URL", "WORLDMONITOR_MCP_URL"),
    )

    severity: SeverityConfig = Field(default_factory=SeverityConfig)
    corroboration: CorroborationConfig = Field(default_factory=CorroborationConfig)
    novelty: NoveltyConfig = Field(default_factory=NoveltyConfig)
    dedup: DedupConfig = Field(default_factory=DedupConfig)

    @property
    def world_monitor_configured(self) -> bool:
        return bool(self.world_monitor_api_key and self.world_monitor_api_key.get_secret_value())

    @model_validator(mode="after")
    def _weights(self) -> WorldSettings:
        n = self.novelty
        total = n.entity_weight + n.location_weight + n.class_weight + n.text_weight
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"novelty weights must sum to 1.0 (got {total:.6f})")
        return self


@lru_cache
def get_world_settings() -> WorldSettings:
    return WorldSettings()
