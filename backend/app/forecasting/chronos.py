"""Optional Chronos-2-Small market-only baseline.

The adapter follows the official Chronos-2 ``Chronos2Pipeline.predict_df`` interface.
It loads local weights only; an unavailable checkpoint is a visible status, never a
silently relabeled forecast.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from importlib.util import find_spec
from typing import Any


@dataclass(frozen=True)
class ChronosPrediction:
    status: str
    q10: float | None = None
    q50: float | None = None
    q90: float | None = None
    cold_ms: float | None = None
    warm_ms: float | None = None
    reason: str | None = None


class Chronos2SmallBaseline:
    model_id = "amazon/chronos-2"

    def __init__(self) -> None:
        self._pipeline: Any | None = None
        self._load_attempted = False
        self._cold_ms: float | None = None
        self._reason: str | None = None

    @property
    def available(self) -> bool:
        return self._pipeline is not None

    def status(self) -> str:
        """Report dependency state without downloading or loading model weights."""
        if self._load_attempted:
            return "AVAILABLE" if self.available else "BASELINE_UNAVAILABLE"
        try:
            return "NOT_LOADED" if find_spec("chronos") is not None else "BASELINE_UNAVAILABLE"
        except (ImportError, ModuleNotFoundError, ValueError):
            return "BASELINE_UNAVAILABLE"

    def load(self) -> str:
        if self._load_attempted:
            return "AVAILABLE" if self.available else "BASELINE_UNAVAILABLE"
        self._load_attempted = True
        started = time.perf_counter()
        try:
            from chronos import Chronos2Pipeline

            self._pipeline = Chronos2Pipeline.from_pretrained(
                self.model_id, device_map="cpu", local_files_only=True
            )
            self._cold_ms = round((time.perf_counter() - started) * 1000, 3)
            return "AVAILABLE"
        except Exception as exc:  # optional dependency/cache failure is an expected state
            self._reason = f"{type(exc).__name__}: {exc}"
            self._pipeline = None
            return "BASELINE_UNAVAILABLE"

    def predict(self, returns: list[float], *, prediction_length: int) -> ChronosPrediction:
        if self.load() != "AVAILABLE":
            return ChronosPrediction(
                "BASELINE_UNAVAILABLE", cold_ms=self._cold_ms, reason=self._reason
            )
        if len(returns) < 8:
            return ChronosPrediction("BASELINE_UNAVAILABLE", reason="insufficient_market_history")
        started = time.perf_counter()
        try:
            import pandas as pd

            base = datetime(2020, 1, 1, tzinfo=UTC)
            frame = pd.DataFrame(
                {
                    "item_id": ["market" for _ in returns],
                    "timestamp": [base + timedelta(days=index) for index in range(len(returns))],
                    "target": returns,
                }
            )
            prediction = self._pipeline.predict_df(
                frame,
                prediction_length=prediction_length,
                quantile_levels=[0.1, 0.5, 0.9],
                freq="D",
            )
            final = prediction.iloc[-prediction_length:]
            values: dict[float, float] = {}
            for level in (0.1, 0.5, 0.9):
                candidates = [
                    column
                    for column in final.columns
                    if str(column) in {str(level), f"target_{level}", f"target__{level}"}
                ]
                if not candidates:
                    raise ValueError(f"Chronos output has no quantile {level}")
                values[level] = float(final[candidates[0]].sum())
            warm_ms = round((time.perf_counter() - started) * 1000, 3)
            return ChronosPrediction(
                "AVAILABLE", values[0.1], values[0.5], values[0.9], self._cold_ms, warm_ms
            )
        except Exception as exc:
            return ChronosPrediction(
                "BASELINE_UNAVAILABLE",
                cold_ms=self._cold_ms,
                reason=f"{type(exc).__name__}: {exc}",
            )
