"""Repeatable, local-only Day 11 microbenchmarks.

The measurements are deliberately scoped to deterministic code paths. They do not imply live
provider, Chronos, ModernFinBERT, or broker performance. Run from the repository root with:
``cd backend && uv run python ../benchmarks/day11.py``.
"""

from __future__ import annotations

import asyncio
import json
import resource
import statistics
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import httpx  # noqa: E402

from app.core.config import Settings  # noqa: E402
from app.graph.propagation import propagate  # noqa: E402
from app.graph.seed import load_seed  # noqa: E402
from app.graph.types import GraphNodeType  # noqa: E402
from app.main import create_app  # noqa: E402
from app.market.pipeline import MarketPipeline  # noqa: E402
from app.market.settings import MarketSettings  # noqa: E402
from app.market.types import Bar, Interval, ProviderName  # noqa: E402
from app.market.universe import get_universe  # noqa: E402
from app.world.fixtures import WORLD_FIXTURES  # noqa: E402
from app.world.normalizer import normalize  # noqa: E402
from app.world.settings import WorldSettings  # noqa: E402
from app.world.text.analyzer import NullAnalyzer  # noqa: E402


def _stats(values: list[float], unit: str = "ms") -> dict[str, float | int | str]:
    if not values:
        return {"status": "UNAVAILABLE", "reason": "no samples"}
    return {
        "status": "MEASURED",
        "samples": len(values),
        "min": round(min(values), 4),
        "p50": round(statistics.median(values), 4),
        "p95": round(sorted(values)[max(0, int(len(values) * 0.95) - 1)], 4),
        "max": round(max(values), 4),
        "unit": unit,
    }


def benchmark_ingest(samples: int = 250) -> dict[str, object]:
    fixture = next(iter(WORLD_FIXTURES.values())).raw
    settings = WorldSettings(_env_file=None)
    values: list[float] = []
    for _ in range(samples):
        started = time.perf_counter()
        normalize(fixture, now=datetime.now(UTC), settings=settings, text_analyzer=NullAnalyzer())
        values.append((time.perf_counter() - started) * 1000)
    result = _stats(values)
    result["throughput_per_second"] = round(samples / (sum(values) / 1000), 2)
    result["scope"] = "pure world normalization, no database"
    return result


def benchmark_graph(samples: int = 250) -> dict[str, object]:
    graph = load_seed()
    channels = [node.id for node in graph.nodes if node.node_type == GraphNodeType.CHANNEL]
    channel = channels[0] if channels else "channel:oil_supply"
    values: list[float] = []
    for _ in range(samples):
        started = time.perf_counter()
        propagate(
            channel_strengths={channel: -0.8},
            event_confidence=0.8,
            nodes=graph.nodes,
            edges=graph.edges,
        )
        values.append((time.perf_counter() - started) * 1000)
    result = _stats(values)
    result["scope"] = (
        f"pure ShockGraph propagation, {len(graph.nodes)} nodes/{len(graph.edges)} edges"
    )
    return result


async def benchmark_stream(samples: int = 5000) -> dict[str, object]:
    pipeline = MarketPipeline(
        SimpleNamespace(name=ProviderName.MASSIVE),
        get_universe(),
        MarketSettings(_env_file=None, echo_market_queue_size=64),
        session_factory=None,
        event_sink=None,
        overflow="drop_oldest",
    )
    started = time.perf_counter()
    timestamp = datetime(2026, 9, 21, 14, 30, tzinfo=UTC)
    for index in range(samples):
        await pipeline._enqueue(
            Bar(
                symbol="AAPL",
                timestamp=timestamp + timedelta(minutes=index),
                interval=Interval.M1,
                open=100.0,
                high=100.1,
                low=99.9,
                close=100.0,
                volume=1.0,
                source=ProviderName.MASSIVE,
            )
        )
    elapsed = time.perf_counter() - started
    return {
        "status": "MEASURED",
        "samples": samples,
        "queue_capacity": pipeline._queue.maxsize,
        "queue_depth": pipeline._queue.qsize(),
        "dropped": pipeline.dropped,
        "throughput_per_second": round(samples / elapsed, 2),
        "elapsed_ms": round(elapsed * 1000, 4),
        "overflow_policy": "drop_oldest",
        "scope": "bounded market pipeline enqueue seam; no provider or database",
    }


async def benchmark_api(samples: int = 100) -> dict[str, object]:
    settings = Settings(_env_file=None, log_level="WARNING")
    app = create_app(settings, manage_db=False)
    values: list[float] = []
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://benchmark"
    ) as client:
        for _ in range(samples):
            started = time.perf_counter()
            response = await client.get("/api/v1/health")
            if response.status_code != 200:
                raise RuntimeError(f"health benchmark returned {response.status_code}")
            values.append((time.perf_counter() - started) * 1000)
    result = _stats(values)
    result["scope"] = "ASGI liveness endpoint, no database or provider"
    return result


def benchmark_forecast(samples: int = 100) -> dict[str, object]:
    """Measure the registered deterministic forecast path; optional Chronos stays separate."""
    artifact_path = ROOT / "artifacts/models/day6-fixture/forecast-bundle.json"
    if not artifact_path.exists():
        return {"status": "UNAVAILABLE", "reason": "registered forecast artifact missing"}
    from app.forecasting.engine import ForecastArtifactBundle, generate_forecast
    from app.forecasting.fixture import fixture_rows
    from app.forecasting.types import FORECAST_HORIZONS
    from app.forecasting.volatility import HARForecast

    bundle = ForecastArtifactBundle.load(artifact_path)
    row = fixture_rows()[0]
    issued = datetime(2025, 1, 2, 14, 30, tzinfo=UTC)
    target_timestamps = {
        horizon: issued + timedelta(days=days)
        for horizon, days in FORECAST_HORIZONS.items()
    }
    volatility = {
        horizon: HARForecast(None, "VOLATILITY_UNAVAILABLE", 0)
        for horizon in FORECAST_HORIZONS
    }
    values: list[float] = []
    for _ in range(samples):
        started = time.perf_counter()
        generate_forecast(
            event_id=str(row["event_id"]),
            symbol=str(row["symbol"]),
            issued_at=issued,
            data_cutoff_at=issued,
            graph_snapshot_id="fixture_graph_v1",
            features=row["features"],  # type: ignore[arg-type]
            bundle=bundle,
            volatility=volatility,
            target_timestamps=target_timestamps,
            event_confidence=0.82,
        )
        values.append((time.perf_counter() - started) * 1000)
    result = _stats(values)
    result["scope"] = "registered linear fallback forecast inference, no Chronos"
    result["artifact_sha256"] = "e1065d87087263b43e7638fe71a86dbf97da00ea99e45e79927a258ba409efcf"
    result["chronos"] = "UNAVAILABLE"
    return result


def memory_report() -> dict[str, object]:
    rss_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return {
        "status": "MEASURED",
        "process_peak_rss_kb": rss_kb,
        "process_peak_rss_mb": round(rss_kb / 1024, 2),
        "scope": "benchmark process without optional model groups",
        "modernfinbert": "NOT_LOADED",
        "chronos": "NOT_LOADED",
    }


async def main() -> None:
    output = {
        "ingestion": benchmark_ingest(),
        "graph": benchmark_graph(),
        "stream": await benchmark_stream(),
        "forecast": benchmark_forecast(),
        "api": await benchmark_api(),
        "memory": memory_report(),
        "recorded_at": datetime.now(UTC).isoformat(),
        "hardware_scope": "local shared development machine; replay-only deterministic paths",
    }
    destination = ROOT / "artifacts/benchmarks/day11"
    destination.mkdir(parents=True, exist_ok=True)
    for name in ("ingestion", "graph", "stream", "forecast", "api", "memory"):
        (destination / f"{name}.json").write_text(
            json.dumps(output[name], indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    (destination / "summary.json").write_text(
        json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(output, indent=2, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(main())
