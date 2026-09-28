#!/usr/bin/env python3
"""Print a secret-free configuration summary."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.config import Settings
from app.execution.settings import ExecutionSettings
from app.graph.backend import resolve_graph_backend
from app.market.settings import MarketSettings
from app.world.settings import WorldSettings
from pydantic import ValidationError


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strict", action="store_true", help="fail when live providers are incomplete")
    args = parser.parse_args()
    try:
        settings = Settings()
        graph = resolve_graph_backend(settings)
        market = MarketSettings()
        world = WorldSettings()
        execution = ExecutionSettings()
    except (ValidationError, ValueError) as exc:
        print(f"Environment: ERROR ({type(exc).__name__})")
        return 1

    failures = 0
    live_market_ready = market.echo_market_provider in {"off", "replay"} or (
        market.echo_market_provider == "massive" and market.massive_configured
    ) or (market.echo_market_provider == "alpaca" and market.alpaca_configured)
    live_world_ready = world.echo_world_provider in {"off", "replay"} or (
        world.echo_world_provider == "world_monitor" and world.world_monitor_configured
    )
    if args.strict:
        failures += int(settings.echo_mode != "live")
        if settings.echo_mode == "live":
            failures += int(not live_market_ready) + int(not live_world_ready)

    print(
        f"Environment: {'OK' if failures == 0 else 'NOT_READY'} "
        f"mode={settings.echo_mode} app_env={settings.app_env}"
    )
    print(
        "Database: "
        f"{settings.database_provider.upper()} configured={'yes' if settings.database_url else 'no'} "
        f"ssl={settings.db_ssl_mode} pool={settings.db_pool_size}+{settings.db_max_overflow}"
    )
    print(f"Graph: {graph.active} state={graph.state} requested={graph.requested}")
    print(
        f"Massive: {'CONFIGURED' if market.massive_configured else 'UNCONFIGURED'} "
        f"selected={market.echo_market_provider}"
    )
    print(
        f"World Monitor: {'CONFIGURED' if world.world_monitor_configured else 'UNCONFIGURED'} "
        f"selected={world.echo_world_provider} mcp={'enabled' if settings.worldmonitor_mcp_enabled else 'disabled'}"
    )
    print(
        f"Alpaca: {'CONFIGURED' if execution.configured else 'UNCONFIGURED'} "
        f"mode={execution.execution_mode} paper_only={'yes' if execution.alpaca_paper else 'no'}"
    )
    print(f"JEV: {'enabled' if settings.jev_enabled else 'disabled'}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
