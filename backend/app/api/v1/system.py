"""Read-only, secret-free system configuration status."""

from fastapi import APIRouter, Request

from app.execution.settings import ExecutionSettings
from app.graph.backend import resolve_graph_backend
from app.market.settings import MarketSettings
from app.world.settings import WorldSettings

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/config-status")
async def config_status(request: Request) -> dict[str, object]:
    settings = request.app.state.settings
    try:
        market = MarketSettings()
        market_status: dict[str, object] = {
            "provider": market.echo_market_provider,
            "configured": (
                market.massive_configured
                if market.echo_market_provider == "massive"
                else market.alpaca_configured
                if market.echo_market_provider == "alpaca"
                else True
            ),
            "state": "CONFIGURED"
            if market.echo_market_provider in {"off", "replay"}
            or (market.echo_market_provider == "massive" and market.massive_configured)
            or (market.echo_market_provider == "alpaca" and market.alpaca_configured)
            else "UNCONFIGURED",
        }
    except Exception:
        market_status = {
            "provider": "invalid",
            "configured": False,
            "state": "ERROR",
            "reason": "invalid configuration",
        }

    try:
        world = WorldSettings()
        world_configured = world.world_monitor_configured
        world_status = {
            "provider": world.echo_world_provider,
            "mcp_enabled": settings.worldmonitor_mcp_enabled,
            "transport": settings.worldmonitor_mcp_transport,
            "configured": (
                world_configured if world.echo_world_provider == "world_monitor" else True
            ),
            "state": "CONFIGURED"
            if world.echo_world_provider in {"off", "replay"}
            or (world.echo_world_provider == "world_monitor" and world_configured)
            else "UNCONFIGURED",
        }
    except Exception:
        world_status = {
            "provider": "invalid",
            "configured": False,
            "state": "ERROR",
            "reason": "invalid configuration",
        }

    try:
        execution = ExecutionSettings()
        execution_status = {
            "mode": execution.execution_mode,
            "configured": execution.configured,
            "paper_only": execution.alpaca_paper,
            "state": "CONFIGURED"
            if execution.execution_mode in {"DISABLED", "REPLAY"}
            or (
                execution.execution_mode == "PAPER"
                and execution.configured
                and execution.alpaca_paper
            )
            else "UNCONFIGURED",
        }
    except Exception:
        execution_status = {
            "mode": "invalid",
            "configured": False,
            "paper_only": False,
            "state": "ERROR",
            "reason": "invalid configuration",
        }

    graph = resolve_graph_backend(settings)
    return {
        "mode": settings.echo_mode,
        "database": {
            "provider": settings.database_provider,
            "configured": bool(settings.database_url),
            "ssl_mode": settings.db_ssl_mode,
        },
        "graph": {
            "requested": graph.requested,
            "active": graph.active,
            "fallback": graph.fallback,
            "state": graph.state,
            "reason": graph.reason,
        },
        "market": market_status,
        "world": world_status,
        "execution": execution_status,
        "optional": {
            "jev_enabled": settings.jev_enabled,
            "massive_repo_configured": settings.massive_repo_path is not None,
            "worldmonitor_repo_configured": settings.worldmonitor_repo_path is not None,
            "alpaca_mcp_enabled": settings.alpaca_mcp_enabled,
        },
    }
