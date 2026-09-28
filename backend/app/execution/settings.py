"""Execution settings with safe disabled defaults."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.config import ROOT_ENV_FILE


class ExecutionSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        populate_by_name=True,
    )

    execution_mode: Literal["DISABLED", "REPLAY", "PAPER", "LIVE"] = Field(
        default="DISABLED", validation_alias=AliasChoices("ECHO_EXECUTION_MODE", "EXECUTION_MODE")
    )
    execution_kill_switch: bool = Field(
        default=False,
        validation_alias=AliasChoices("ECHO_EXECUTION_KILL_SWITCH", "EXECUTION_KILL_SWITCH"),
    )
    alpaca_api_key: SecretStr | None = None
    alpaca_api_secret: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("ALPACA_API_SECRET", "ALPACA_SECRET_KEY"),
    )
    alpaca_paper: bool = Field(
        default=True,
        validation_alias=AliasChoices("ALPACA_PAPER", "ALPACA_PAPER_TRADE"),
    )
    allowed_symbols: str = ""
    market_data_max_age_seconds: int = 90

    @model_validator(mode="after")
    def _safe(self) -> ExecutionSettings:
        if self.execution_mode == "LIVE":
            raise ValueError("LIVE execution is not supported; use PAPER or REPLAY")
        if self.execution_mode == "PAPER" and not self.alpaca_paper:
            raise ValueError("paper execution requires ALPACA_PAPER=true")
        if self.market_data_max_age_seconds <= 0:
            raise ValueError("market_data_max_age_seconds must be positive")
        return self

    @property
    def configured(self) -> bool:
        return bool(self.alpaca_api_key and self.alpaca_api_secret)

    def symbols(self) -> frozenset[str]:
        return frozenset(
            item.strip().upper() for item in self.allowed_symbols.split(",") if item.strip()
        )


@lru_cache
def get_execution_settings() -> ExecutionSettings:
    return ExecutionSettings()
