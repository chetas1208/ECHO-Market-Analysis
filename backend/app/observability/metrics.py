"""Small dependency-free Prometheus registry.

The service intentionally does not require a metrics package for local replay mode.  Labels are
kept explicit and bounded at call sites; this registry only handles aggregation and exposition.
"""

from __future__ import annotations

import math
import threading
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


def _label_value(value: object) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _labels(labels: Mapping[str, object] | None) -> tuple[tuple[str, str], ...]:
    if not labels:
        return ()
    return tuple(sorted((str(key), _label_value(value)) for key, value in labels.items()))


def _label_text(labels: tuple[tuple[str, str], ...]) -> str:
    if not labels:
        return ""
    return "{" + ",".join(f'{key}="{value}"' for key, value in labels) + "}"


@dataclass(frozen=True)
class HistogramSnapshot:
    buckets: tuple[tuple[float, int], ...]
    count: int
    total: float


class MetricsRegistry:
    """Thread-safe counters, gauges, and bounded histograms."""

    DEFAULT_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[tuple[str, tuple[tuple[str, str], ...]], float] = defaultdict(float)
        self._gauges: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {}
        self._histograms: dict[tuple[str, tuple[tuple[str, str], ...]], HistogramSnapshot] = {}
        self._help: dict[str, str] = {}

    def inc(
        self,
        name: str,
        value: float = 1.0,
        *,
        labels: Mapping[str, object] | None = None,
        help_text: str = "",
    ) -> None:
        if not math.isfinite(value):
            return
        key = (name, _labels(labels))
        with self._lock:
            self._counters[key] += value
            if help_text:
                self._help[name] = help_text

    def set(
        self,
        name: str,
        value: float,
        *,
        labels: Mapping[str, object] | None = None,
        help_text: str = "",
    ) -> None:
        if not math.isfinite(value):
            return
        key = (name, _labels(labels))
        with self._lock:
            self._gauges[key] = value
            if help_text:
                self._help[name] = help_text

    def observe(
        self,
        name: str,
        value: float,
        *,
        labels: Mapping[str, object] | None = None,
        buckets: tuple[float, ...] | None = None,
        help_text: str = "",
    ) -> None:
        if not math.isfinite(value) or value < 0:
            return
        limits = tuple(sorted(buckets or self.DEFAULT_BUCKETS))
        key = (name, _labels(labels))
        with self._lock:
            previous = self._histograms.get(key)
            counts = dict(previous.buckets) if previous else {limit: 0 for limit in limits}
            for limit in limits:
                if value <= limit:
                    counts[limit] = counts.get(limit, 0) + 1
            self._histograms[key] = HistogramSnapshot(
                tuple(sorted(counts.items())),
                (previous.count if previous else 0) + 1,
                (previous.total if previous else 0.0) + value,
            )
            if help_text:
                self._help[name] = help_text

    def snapshot(self) -> dict[str, Any]:
        """Return a test/debug-friendly immutable-ish view of current values."""
        with self._lock:
            return {
                "counters": dict(self._counters),
                "gauges": dict(self._gauges),
                "histograms": dict(self._histograms),
            }

    def render(self) -> str:
        lines: list[str] = []
        with self._lock:
            counters = dict(self._counters)
            gauges = dict(self._gauges)
            histograms = dict(self._histograms)
            help_map = dict(self._help)
        names = {name for name, _ in (*counters.keys(), *gauges.keys(), *histograms.keys())}
        for name in sorted(names):
            if name in help_map:
                lines.append(f"# HELP {name} {help_map[name]}")
            kind = (
                "histogram"
                if any(key[0] == name for key in histograms)
                else ("counter" if any(key[0] == name for key in counters) else "gauge")
            )
            lines.append(f"# TYPE {name} {kind}")
            for (metric, labels), value in sorted(counters.items()):
                if metric == name:
                    lines.append(f"{metric}{_label_text(labels)} {value:g}")
            for (metric, labels), value in sorted(gauges.items()):
                if metric == name:
                    lines.append(f"{metric}{_label_text(labels)} {value:g}")
            for (metric, labels), histogram in sorted(histograms.items()):
                if metric != name:
                    continue
                for limit, count in histogram.buckets:
                    bucket_labels = (*labels, ("le", str(limit)))
                    lines.append(f"{metric}_bucket{_label_text(bucket_labels)} {count}")
                lines.append(
                    f"{metric}_bucket{_label_text((*labels, ('le', '+Inf')))} {histogram.count}"
                )
                lines.append(f"{metric}_count{_label_text(labels)} {histogram.count}")
                lines.append(f"{metric}_sum{_label_text(labels)} {histogram.total:g}")
        return "\n".join(lines) + ("\n" if lines else "")


def collect_runtime_metrics(registry: MetricsRegistry, app: Any) -> None:
    """Refresh gauges from runtime facades immediately before exposition."""
    registry.set(
        "echo_build_info", 1, labels={"version": "0.2.0-dev"}, help_text="ECHO build metadata."
    )
    forecast_available = get_forecast_artifact_available()
    registry.set(
        "echo_model_state",
        1,
        labels={
            "model": "echo-forecast-linear-pinball",
            "status": "READY" if forecast_available else "UNAVAILABLE",
        },
        help_text="Current model availability state.",
    )
    registry.set(
        "echo_model_state",
        1,
        labels={"model": "chronos-2", "status": "UNAVAILABLE"},
        help_text="Current model availability state.",
    )
    for resource in ("rss", "inference"):
        registry.set(
            "echo_model_measurement_available",
            0,
            labels={"model": "chronos-2", "resource": resource},
            help_text="Whether a runtime model resource measurement is available.",
        )
    market = getattr(app.state, "market_runtime", None)
    if market is not None:
        try:
            status = market.status()
            registry.set(
                "echo_market_queue_depth", status.queue_depth, help_text="Market queue depth."
            )
            registry.set(
                "echo_market_queue_capacity",
                status.queue_capacity,
                help_text="Market queue capacity.",
            )
            registry.set(
                "echo_market_messages_dropped_total",
                status.dropped,
                help_text="Market messages dropped by the bounded queue.",
            )
            for provider in status.providers:
                registry.set(
                    "echo_provider_state",
                    1,
                    labels={
                        "domain": "market",
                        "provider": provider.provider.value,
                        "state": provider.state.value,
                    },
                    help_text="Current provider state; one series is emitted per observed state.",
                )
                registry.set(
                    "echo_provider_messages_total",
                    provider.messages_received,
                    labels={"domain": "market", "provider": provider.provider.value},
                    help_text="Normalized market messages received.",
                )
        except Exception:
            pass
    world = getattr(app.state, "world_runtime", None)
    if world is not None:
        try:
            health = world.health()
            analyzer_status = str(getattr(world, "analyzer_status", "DISABLED")).upper()
            registry.set(
                "echo_model_state",
                1,
                labels={"model": "modernfinbert", "status": analyzer_status},
                help_text="Current model availability state.",
            )
            registry.set(
                "echo_provider_state",
                1,
                labels={
                    "domain": "world",
                    "provider": health.provider.value,
                    "state": health.state.value,
                },
                help_text="Current provider state; one series is emitted per observed state.",
            )
            counters = world.counters()
            for name in ("received", "created", "merged", "duplicates", "rejected"):
                registry.set(
                    f"echo_world_events_{name}_total",
                    float(counters.get(name, 0)),
                    help_text="World event pipeline counters.",
                )
        except Exception:
            pass
    execution = getattr(app.state, "execution_service", None)
    if execution is not None:
        try:
            health = execution.health(data_fresh=False)
            registry.set(
                "echo_execution_kill_switch",
                int(health.kill_switch),
                help_text="Whether paper execution is paused.",
            )
            registry.set(
                "echo_execution_healthy",
                int(health.healthy),
                labels={"provider": health.provider},
                help_text="Execution provider health.",
            )
            registry.set(
                "echo_execution_reconciliation_mismatch",
                int(health.reconciliation_state == "DEGRADED"),
                help_text="Whether reconciliation has a mismatch.",
            )
        except Exception:
            pass
    engine = getattr(app.state, "engine", None)
    if engine is not None:
        try:
            pool = engine.sync_engine.pool
            registry.set(
                "echo_db_pool_size", float(pool.size()), help_text="Configured database pool size."
            )
            registry.set(
                "echo_db_pool_checked_out",
                float(pool.checkedout()),
                help_text="Database connections checked out.",
            )
            registry.set(
                "echo_db_pool_overflow",
                float(pool.overflow()),
                help_text="Database pool overflow connections.",
            )
        except (AttributeError, RuntimeError):
            pass


def get_forecast_artifact_available() -> bool:
    """Check the registered artifact without loading model weights during a scrape."""
    try:
        from app.core.config import get_settings

        return get_settings().forecast_artifact_path.exists()
    except Exception:
        return False
