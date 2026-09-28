"""Append-only forecast vintages, actual observations, and evaluations."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError
from app.forecasting.types import FORECAST_HORIZONS, ForecastResult
from app.models import (
    CanonicalEvent,
    ForecastActual,
    ForecastEvaluation,
    ForecastPoint,
    ForecastRun,
)
from app.schemas.forecast import ForecastPreviewOut

ENGINE_VERSION = "echo-ledger-v1"
DEFAULT_CONFIG_HASH = hashlib.sha256(b"echo-forecast-config-v1").hexdigest()


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(UTC)


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str, allow_nan=False)


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def event_snapshot(event: CanonicalEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "timestamp": _utc(event.timestamp).isoformat(),
        "source_type": event.source_type,
        "event_type": event.event_type,
        "title": event.title,
        "summary": event.summary,
        "entities": event.entities,
        "companies": event.companies,
        "locations": event.locations,
        "economic_channels": event.economic_channels,
        "severity": event.severity,
        "novelty": event.novelty,
        "corroboration": event.corroboration,
        "confidence": event.confidence,
        "source_refs": event.source_refs,
        "metadata": event.metadata_,
        "revision": event.revision,
        "source_count": event.source_count,
        "independent_source_count": event.independent_source_count,
    }


def _feature_snapshot(preview: ForecastPreviewOut) -> dict[str, float | None]:
    value = preview.diagnostics.get("feature_snapshot", {})
    if not isinstance(value, dict):
        raise ConflictError("forecast preview is missing its feature snapshot")
    snapshot: dict[str, float | None] = {}
    for name, item in value.items():
        if not isinstance(name, str) or (item is not None and not isinstance(item, (int, float))):
            raise ConflictError("forecast feature snapshot is invalid")
        snapshot[name] = None if item is None else float(item)
    if ForecastResult.hash_features(snapshot) != preview.feature_hash:
        raise ConflictError("forecast feature hash does not match its feature snapshot")
    return snapshot


def _point_material(point: ForecastPoint) -> dict[str, Any]:
    return {
        "horizon": point.horizon,
        "horizon_trading_days": point.horizon_trading_days,
        "target_timestamp": _utc(point.target_timestamp).isoformat(),
        "q10": point.q10,
        "q50": point.q50,
        "q90": point.q90,
        "probability_positive": point.probability_positive,
        "expected_abnormal_return": point.expected_abnormal_return,
        "forecast_risk": point.forecast_risk,
    }


def _run_material(run: ForecastRun, points: list[ForecastPoint]) -> dict[str, Any]:
    return {
        "event_id": run.event_id,
        "symbol": run.symbol,
        "prediction_timestamp": _utc(run.prediction_timestamp).isoformat(),
        "data_cutoff_at": _utc(run.data_cutoff_at).isoformat(),
        "graph_snapshot_id": run.graph_snapshot_id,
        "event_snapshot_id": run.event_snapshot_id,
        "event_snapshot": run.event_snapshot,
        "model_version": run.model_version,
        "feature_version": run.feature_version,
        "model_artifact_hash": run.model_artifact_hash,
        "feature_hash": run.feature_hash,
        "feature_snapshot": run.feature_snapshot,
        "config_hash": run.config_hash,
        "forecasting_engine_version": run.forecasting_engine_version,
        "recommended_horizon": run.recommended_horizon,
        "information_half_life": run.information_half_life,
        "ood_status": run.ood_status,
        "abstention_state": run.abstention_state,
        "points": [_point_material(point) for point in points],
    }


def _event_out(event: CanonicalEvent | None) -> dict[str, Any] | None:
    return event_snapshot(event) if event is not None else None


class PredictionLedgerService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_vintage(
        self,
        preview: ForecastPreviewOut,
        event: CanonicalEvent,
        *,
        config_hash: str = DEFAULT_CONFIG_HASH,
        forecasting_engine_version: str = ENGINE_VERSION,
        idempotency_key: str | None = None,
        commit: bool = True,
    ) -> ForecastRun:
        if preview.model_status != "READY" or not preview.horizons:
            raise ConflictError("only a READY forecast can become a ledger vintage")
        features = _feature_snapshot(preview)
        snapshot = event_snapshot(event)
        request_material = {
            "event_id": preview.event_id,
            "symbol": preview.symbol.upper(),
            "issued_at": _utc(preview.issued_at).isoformat(),
            "data_cutoff_at": _utc(preview.data_cutoff_at).isoformat(),
            "graph_snapshot_id": preview.graph_snapshot_id,
            "model_version": preview.model_version,
            "feature_version": preview.feature_version,
            "feature_hash": preview.feature_hash,
            "model_artifact_hash": preview.model_artifact_hash,
            "config_hash": config_hash,
            "engine_version": forecasting_engine_version,
            "horizons": preview.horizons,
        }
        request_hash = _hash(request_material)
        if idempotency_key:
            existing = await self.session.scalar(
                select(ForecastRun).where(ForecastRun.idempotency_key == idempotency_key)
            )
            if existing is not None:
                if existing.request_hash != request_hash:
                    raise ConflictError("idempotency key was already used for another forecast")
                return existing
        existing = await self.session.scalar(
            select(ForecastRun).where(ForecastRun.request_hash == request_hash)
        )
        if existing is not None:
            return existing

        run = ForecastRun(
            id=uuid.uuid4(),
            event_id=event.id,
            symbol=preview.symbol.upper(),
            prediction_timestamp=_utc(preview.issued_at),
            data_cutoff_at=_utc(preview.data_cutoff_at),
            model_version=preview.model_version,
            feature_version=preview.feature_version,
            graph_snapshot_id=preview.graph_snapshot_id,
            event_snapshot_id=f"event-{_hash(snapshot)[:24]}",
            feature_hash=preview.feature_hash,
            model_artifact_hash=preview.model_artifact_hash
            or str(preview.diagnostics.get("artifact_hash") or ""),
            config_hash=config_hash,
            forecasting_engine_version=forecasting_engine_version,
            recommended_horizon=preview.recommended_horizon,
            information_half_life=preview.information_half_life,
            ood_status=str(preview.diagnostics.get("ood", "UNKNOWN")),
            abstention_state="NONE",
            request_hash=request_hash,
            idempotency_key=idempotency_key,
            event_snapshot=snapshot,
            feature_snapshot=features,
        )
        points: list[ForecastPoint] = []
        for horizon, value in preview.horizons.items():
            if (
                horizon not in FORECAST_HORIZONS
                or value.q10 is None
                or value.q50 is None
                or value.q90 is None
            ):
                continue
            points.append(
                ForecastPoint(
                    forecast_run_id=run.id,
                    horizon=horizon,
                    horizon_trading_days=FORECAST_HORIZONS[horizon],
                    target_timestamp=_utc(value.target_timestamp)
                    if value.target_timestamp
                    else run.prediction_timestamp,
                    q10=value.q10,
                    q50=value.q50,
                    q90=value.q90,
                    probability_positive=value.probability_positive or 0.0,
                    expected_abnormal_return=value.q50,
                    forecast_risk=value.risk,
                )
            )
        # Compute the immutable content hash before INSERT. Updating a ledger row
        # after INSERT would correctly be rejected by the PostgreSQL trigger.
        run.content_hash = _hash(_run_material(run, points))
        self.session.add(run)
        await self.session.flush()
        self.session.add_all(points)
        await self.session.flush()
        if not commit:
            return run
        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            existing = await self.session.scalar(
                select(ForecastRun).where(ForecastRun.request_hash == request_hash)
            )
            if existing is not None:
                return existing
            raise ConflictError("forecast vintage could not be created") from exc
        return run

    async def get_vintage(self, forecast_id: uuid.UUID) -> tuple[ForecastRun, list[ForecastPoint]]:
        run = await self.session.get(ForecastRun, forecast_id)
        if run is None:
            raise NotFoundError(f"Forecast vintage '{forecast_id}' not found")
        points = list(
            (
                await self.session.scalars(
                    select(ForecastPoint)
                    .where(ForecastPoint.forecast_run_id == forecast_id)
                    .order_by(ForecastPoint.horizon_trading_days)
                )
            ).all()
        )
        return run, points

    async def list_vintages(
        self,
        *,
        symbol: str | None = None,
        event_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[ForecastRun], int]:
        conditions = []
        if symbol:
            conditions.append(ForecastRun.symbol == symbol.strip().upper())
        if event_id:
            conditions.append(ForecastRun.event_id == event_id)
        items = list(
            (
                await self.session.scalars(
                    select(ForecastRun)
                    .where(*conditions)
                    .order_by(ForecastRun.prediction_timestamp.desc(), ForecastRun.id.desc())
                    .offset(max(0, offset))
                    .limit(max(1, min(limit, 200)))
                )
            ).all()
        )
        from sqlalchemy import func

        total = await self.session.scalar(
            select(func.count()).select_from(ForecastRun).where(*conditions)
        )
        return items, int(total or 0)

    async def append_actual(
        self, forecast_id: uuid.UUID, values: dict[str, Any], *, commit: bool = True
    ) -> ForecastActual:
        run = await self.session.get(ForecastRun, forecast_id)
        if run is None:
            raise NotFoundError(f"Forecast vintage '{forecast_id}' not found")
        market_timestamp = _utc(values["market_timestamp"])
        observed_at = _utc(values["observed_at"])
        if market_timestamp <= _utc(run.data_cutoff_at):
            raise ConflictError("actual observation must be after the forecast data cutoff")
        if observed_at < market_timestamp:
            raise ConflictError("observation timestamp cannot precede market timestamp")
        material = {
            "forecast_run_id": str(forecast_id),
            "symbol": str(values["symbol"]).upper(),
            "horizon": values["horizon"],
            "market_timestamp": market_timestamp.isoformat(),
            "actual_price": values.get("actual_price"),
            "actual_return": values.get("actual_return"),
            "actual_abnormal_return": values.get("actual_abnormal_return"),
            "market_return": values.get("market_return"),
            "sector_return": values.get("sector_return"),
            "source": values["source"],
        }
        observation_hash = _hash(material)
        existing = await self.session.scalar(
            select(ForecastActual).where(ForecastActual.observation_hash == observation_hash)
        )
        if existing is not None:
            return existing
        existing_at_timestamp = await self.session.scalar(
            select(ForecastActual).where(
                ForecastActual.forecast_run_id == forecast_id,
                ForecastActual.horizon == values["horizon"],
                ForecastActual.market_timestamp == market_timestamp,
            )
        )
        if existing_at_timestamp is not None:
            return existing_at_timestamp
        actual = ForecastActual(
            forecast_run_id=forecast_id,
            symbol=str(values["symbol"]).upper(),
            horizon=values["horizon"],
            observed_at=observed_at,
            market_timestamp=market_timestamp,
            actual_price=values.get("actual_price"),
            actual_return=values.get("actual_return"),
            actual_abnormal_return=values.get("actual_abnormal_return"),
            market_return=values.get("market_return"),
            sector_return=values.get("sector_return"),
            source=values["source"],
            observation_hash=observation_hash,
        )
        self.session.add(actual)
        if not commit:
            await self.session.flush()
            return actual
        try:
            await self.session.flush()
            for row in await self.evaluate(forecast_id):
                if row["status"] != "COMPLETE":
                    continue
                if await self.session.scalar(
                    select(ForecastEvaluation).where(
                        ForecastEvaluation.evaluation_hash == row["evaluation_hash"]
                    )
                ):
                    continue
                self.session.add(
                    ForecastEvaluation(
                        forecast_run_id=forecast_id,
                        horizon=row["horizon"],
                        evaluated_at=row["evaluated_at"],
                        status=row["status"],
                        predicted_q10=row["predicted_q10"],
                        predicted_q50=row["predicted_q50"],
                        predicted_q90=row["predicted_q90"],
                        probability_positive=row["probability_positive"],
                        actual_abnormal_return=row["actual_abnormal_return"],
                        absolute_error=row["absolute_error"],
                        squared_error=row["squared_error"],
                        directional_correct=row["directional_correct"],
                        interval_covered=row["interval_covered"],
                        pinball_q10=row["pinball_q10"],
                        pinball_q50=row["pinball_q50"],
                        pinball_q90=row["pinball_q90"],
                        brier_contribution=row["brier_contribution"],
                        evaluation_hash=row["evaluation_hash"],
                    )
                )
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            existing = await self.session.scalar(
                select(ForecastActual).where(ForecastActual.observation_hash == observation_hash)
            )
            if existing is not None:
                return existing
            existing_at_timestamp = await self.session.scalar(
                select(ForecastActual).where(
                    ForecastActual.forecast_run_id == forecast_id,
                    ForecastActual.horizon == values["horizon"],
                    ForecastActual.market_timestamp == market_timestamp,
                )
            )
            if existing_at_timestamp is not None:
                return existing_at_timestamp
            raise ConflictError("actual observation could not be appended") from exc
        return actual

    async def list_actuals(self, forecast_id: uuid.UUID) -> list[ForecastActual]:
        await self.get_vintage(forecast_id)
        return list(
            (
                await self.session.scalars(
                    select(ForecastActual)
                    .where(ForecastActual.forecast_run_id == forecast_id)
                    .order_by(ForecastActual.market_timestamp, ForecastActual.created_at)
                )
            ).all()
        )

    @staticmethod
    def _pinball(actual: float, predicted: float, alpha: float) -> float:
        error = actual - predicted
        return alpha * error if error >= 0 else (alpha - 1) * error

    async def evaluate(self, forecast_id: uuid.UUID) -> list[dict[str, Any]]:
        run, points = await self.get_vintage(forecast_id)
        actuals = await self.list_actuals(forecast_id)
        by_horizon: dict[str, ForecastActual] = {}
        for actual in actuals:
            if actual.horizon in FORECAST_HORIZONS and actual.actual_abnormal_return is not None:
                by_horizon.setdefault(actual.horizon, actual)
        output: list[dict[str, Any]] = []
        for point in points:
            actual = by_horizon.get(point.horizon)
            status = "COMPLETE" if actual else "PENDING"
            row: dict[str, Any] = {
                "forecast_run_id": str(run.id),
                "horizon": point.horizon,
                "status": status,
                "evaluated_at": datetime.now(UTC),
                "predicted_q10": point.q10,
                "predicted_q50": point.q50,
                "predicted_q90": point.q90,
                "probability_positive": point.probability_positive,
                "actual_abnormal_return": None,
                "absolute_error": None,
                "squared_error": None,
                "directional_correct": None,
                "interval_covered": None,
                "pinball_q10": None,
                "pinball_q50": None,
                "pinball_q90": None,
                "brier_contribution": None,
            }
            if actual is not None:
                realized = float(actual.actual_abnormal_return)
                error = float(point.q50) - realized
                row.update(
                    actual_abnormal_return=realized,
                    absolute_error=abs(error),
                    squared_error=error * error,
                    directional_correct=(float(point.q50) == 0 and realized == 0)
                    or (float(point.q50) > 0 and realized > 0)
                    or (float(point.q50) < 0 and realized < 0),
                    interval_covered=float(point.q10) <= realized <= float(point.q90),
                    pinball_q10=self._pinball(realized, float(point.q10), 0.1),
                    pinball_q50=self._pinball(realized, float(point.q50), 0.5),
                    pinball_q90=self._pinball(realized, float(point.q90), 0.9),
                    brier_contribution=(
                        float(point.probability_positive) - (1.0 if realized > 0 else 0.0)
                    )
                    ** 2,
                )
            row["evaluation_hash"] = _hash(
                {k: str(v) for k, v in row.items() if k != "evaluated_at"}
            )
            output.append(row)
        return output

    async def verify_integrity(self, forecast_id: uuid.UUID) -> dict[str, Any]:
        run, points = await self.get_vintage(forecast_id)
        expected = _hash(_run_material(run, points))
        return {
            "forecast_id": str(forecast_id),
            "status": "VALID" if expected == run.content_hash else "CORRUPT",
            "stored_content_hash": run.content_hash,
            "computed_content_hash": expected,
            "model_version": run.model_version,
            "model_artifact_hash": run.model_artifact_hash,
            "feature_hash": run.feature_hash,
            "graph_snapshot_id": run.graph_snapshot_id,
        }

    async def export(self, forecast_id: uuid.UUID) -> dict[str, Any]:
        run, points = await self.get_vintage(forecast_id)
        actuals = await self.list_actuals(forecast_id)
        evaluations = await self.evaluate(forecast_id)
        for evaluation in evaluations:
            evaluation["evaluated_at"] = _utc(evaluation["evaluated_at"]).isoformat()
        return {
            "forecast": {
                "id": str(run.id),
                **_run_material(run, points),
                "created_at": _utc(run.created_at).isoformat(),
                "content_hash": run.content_hash,
                "request_hash": run.request_hash,
            },
            "actuals": [
                {
                    "id": str(actual.id),
                    "horizon": actual.horizon,
                    "observed_at": _utc(actual.observed_at).isoformat(),
                    "market_timestamp": _utc(actual.market_timestamp).isoformat(),
                    "actual_price": actual.actual_price,
                    "actual_return": actual.actual_return,
                    "actual_abnormal_return": actual.actual_abnormal_return,
                    "market_return": actual.market_return,
                    "sector_return": actual.sector_return,
                    "source": actual.source,
                    "observation_hash": actual.observation_hash,
                }
                for actual in actuals
            ],
            "evaluations": evaluations,
            "integrity": await self.verify_integrity(forecast_id),
        }
