"""Application settings.

Reads the repository-root ``.env`` (if present) and process environment variables;
environment variables win. Secret values are accepted only for optional services and
are never included in status responses or logs.
"""

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# backend/app/core/config.py -> repo root is three levels above `app/`.
ROOT_ENV_FILE = Path(__file__).resolve().parents[3] / ".env"

DEFAULT_DATABASE_URL = "postgresql+asyncpg://echo:echo_dev_password@localhost:5433/echo"
DEFAULT_CORS_ORIGINS = ["http://localhost:3000", "http://127.0.0.1:3000"]
REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_FORECAST_ARTIFACT = REPO_ROOT / "artifacts" / "models" / "forecast-bundle.json"
DEMO_FORECAST_ARTIFACT = (
    REPO_ROOT / "artifacts" / "models" / "day6-fixture" / "forecast-bundle.json"
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: str = "development"
    log_level: str = "INFO"
    service_name: str = "echo-api"

    # Runtime mode is deliberately explicit. Provider-specific settings remain
    # independently selectable for backwards compatibility with Day 2/3.
    echo_mode: Literal["live", "replay", "offline"] = "offline"

    database_url: str = DEFAULT_DATABASE_URL
    database_direct_url: str | None = None
    database_provider: Literal["local", "neon"] = "local"
    db_pool_size: int = 5
    db_max_overflow: int = 5
    db_pool_timeout: int = 30
    db_pool_recycle: int = 300
    db_ssl_mode: Literal["disable", "prefer", "require"] = "prefer"

    # ShockGraph is currently implemented by the bounded deterministic graph
    # service. AURE is an optional local store selected only when explicitly
    # enabled and its real CLI/database paths are supplied.
    graph_backend: Literal["aure", "networkx"] = "networkx"
    graph_fallback_backend: Literal["none", "networkx"] = "networkx"
    aure_enabled: bool = False
    aure_binary: Path | None = None
    aure_database_path: Path | None = None
    aure_config_path: Path | None = None
    aure_query_timeout_seconds: int = 5

    massive_repo_path: Path | None = None
    worldmonitor_repo_path: Path | None = None
    alpaca_mcp_repo_path: Path | None = None
    worldmonitor_mcp_enabled: bool = False
    worldmonitor_mcp_url: str = "https://worldmonitor.app/mcp"
    worldmonitor_mcp_transport: Literal["streamable_http", "stdio"] = "streamable_http"
    alpaca_mcp_enabled: bool = False
    alpaca_toolsets: str = "account,trading,assets,stock-data"
    jev_enabled: bool = False
    jev_api_key: SecretStr | None = None
    jev_model: str = "typesafe/jev-1.13"

    api_host: str = "127.0.0.1"
    api_port: int = 8100
    forecast_artifact_path: Path = (
        DEFAULT_FORECAST_ARTIFACT if DEFAULT_FORECAST_ARTIFACT.exists() else DEMO_FORECAST_ARTIFACT
    )

    cors_allow_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: list(DEFAULT_CORS_ORIGINS)
    )

    @field_validator("database_url")
    @classmethod
    def _async_driver(cls, value: str) -> str:
        if value.startswith("postgresql://"):
            return value.replace("postgresql://", "postgresql+asyncpg://", 1)
        if value.startswith("postgres://"):
            return value.replace("postgres://", "postgresql+asyncpg://", 1)
        return value

    @field_validator("cors_allow_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            value = [item.strip() for item in value.split(",")]
        if isinstance(value, list):
            origins = [str(item).strip().rstrip("/") for item in value if str(item).strip()]
            if "*" in origins:
                raise ValueError("CORS_ALLOW_ORIGINS must be explicit origins, '*' is not allowed")
            return origins
        return value

    @field_validator("log_level")
    @classmethod
    def _upper_level(cls, value: str) -> str:
        return value.upper()

    @field_validator(
        "database_direct_url",
        "aure_binary",
        "aure_database_path",
        "aure_config_path",
        "massive_repo_path",
        "worldmonitor_repo_path",
        "alpaca_mcp_repo_path",
        mode="before",
    )
    @classmethod
    def _empty_optional_path(cls, value: object) -> object:
        return None if value is None or (isinstance(value, str) and not value.strip()) else value

    @field_validator(
        "db_pool_size",
        "db_max_overflow",
        "db_pool_timeout",
        "db_pool_recycle",
        "aure_query_timeout_seconds",
    )
    @classmethod
    def _positive_runtime_values(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("runtime pool and timeout values must be positive")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
