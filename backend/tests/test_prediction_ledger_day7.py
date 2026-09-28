import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.forecasting.types import ForecastResult
from app.models import CanonicalEvent
from app.schemas.forecast import ForecastHorizonOut, ForecastPreviewOut
from app.services.prediction_ledger import PredictionLedgerService
from tests.conftest import unique_event_id

T0 = datetime(2026, 9, 20, 17, 0, tzinfo=UTC)


@pytest_asyncio.fixture
async def session(engine: AsyncEngine):
    async with engine.connect() as connection:
        transaction = await connection.begin()
        async_session = AsyncSession(bind=connection, expire_on_commit=False)
        try:
            yield async_session
        finally:
            await async_session.rollback()
            await async_session.close()
            if transaction.is_active:
                await transaction.rollback()


def preview(event_id: str) -> ForecastPreviewOut:
    features = {"beta_market": 1.0, "beta_sector": 0.5, "graph_exposure": 0.2}
    horizons = {}
    for name, days in (("1D", 1), ("2D", 2), ("5D", 5), ("10D", 10), ("20D", 20)):
        horizons[name] = ForecastHorizonOut(
            horizon=name,
            trading_days=days,
            target_timestamp=T0 + timedelta(days=days),
            q10=-0.02,
            q50=0.01,
            q90=0.04,
            probability_positive=0.7,
            risk=0.02,
            confidence=0.8,
            score=0.1,
        )
    return ForecastPreviewOut(
        event_id=event_id,
        symbol="NVDA",
        issued_at=T0,
        data_cutoff_at=T0,
        graph_snapshot_id="g1",
        model_version="m1",
        feature_version="echo-features-v1",
        feature_hash=ForecastResult.hash_features(features),
        model_artifact_hash="a" * 64,
        horizons=horizons,
        recommended_horizon="1D",
        information_half_life=None,
        model_status="READY",
        diagnostics={"ood": "IN_DISTRIBUTION", "feature_snapshot": features},
    )


async def make_event(session: AsyncSession, event_id: str) -> CanonicalEvent:
    event = CanonicalEvent(
        id=event_id,
        timestamp=T0,
        source_type="WORLD",
        event_type="supply_disruption",
        title="Ledger test event",
        severity=0.5,
        novelty=0.5,
        corroboration=0.5,
        confidence=0.8,
    )
    session.add(event)
    await session.flush()
    return event


@pytest.mark.asyncio
async def test_vintage_is_idempotent_and_integrity_is_stable(session: AsyncSession) -> None:
    event_id = unique_event_id("day7")
    event = await make_event(session, event_id)
    service = PredictionLedgerService(session)
    first = await service.create_vintage(
        preview(event_id),
        event,
        config_hash="echo-config-hash-v1",
        idempotency_key="retry-1",
        commit=False,
    )
    second = await service.create_vintage(
        preview(event_id),
        event,
        config_hash="echo-config-hash-v1",
        idempotency_key="retry-1",
        commit=False,
    )
    assert first.id == second.id
    integrity = await service.verify_integrity(first.id)
    assert integrity["status"] == "VALID"
    assert integrity["stored_content_hash"] == integrity["computed_content_hash"]
    assert len((await service.get_vintage(first.id))[1]) == 5


@pytest.mark.asyncio
async def test_actual_before_cutoff_is_rejected(session: AsyncSession) -> None:
    event_id = unique_event_id("day7cutoff")
    event = await make_event(session, event_id)
    service = PredictionLedgerService(session)
    run = await service.create_vintage(
        preview(event_id), event, config_hash="echo-config-hash-v2", commit=False
    )
    with pytest.raises(Exception, match="after the forecast data cutoff"):
        await service.append_actual(
            run.id,
            {
                "symbol": "NVDA",
                "horizon": "1D",
                "observed_at": T0,
                "market_timestamp": T0,
                "actual_price": 100,
                "actual_abnormal_return": 0.01,
                "source": "test",
            },
        )


@pytest.mark.asyncio
async def test_actual_evaluation_uses_abnormal_return_units(session: AsyncSession) -> None:
    event_id = unique_event_id("day7eval")
    event = await make_event(session, event_id)
    service = PredictionLedgerService(session)
    run = await service.create_vintage(
        preview(event_id), event, config_hash="echo-config-hash-v3", commit=False
    )
    actual = await service.append_actual(
        run.id,
        {
            "symbol": "NVDA",
            "horizon": "1D",
            "observed_at": T0 + timedelta(days=1, minutes=2),
            "market_timestamp": T0 + timedelta(days=1),
            "actual_price": 101,
            "actual_abnormal_return": 0.02,
            "source": "test",
        },
        commit=False,
    )
    assert actual.actual_abnormal_return == 0.02
    rows = await service.evaluate(run.id)
    one_day = next(row for row in rows if row["horizon"] == "1D")
    assert one_day["status"] == "COMPLETE"
    assert one_day["actual_abnormal_return"] == 0.02
    assert one_day["absolute_error"] == 0.01


async def test_new_ledger_tables_are_database_immutable(engine: AsyncEngine) -> None:
    async with engine.connect() as connection:
        transaction = await connection.begin()
        try:
            run_id = uuid.uuid4()
            await connection.execute(
                text(
                    "INSERT INTO forecast_runs "
                    "(id, symbol, prediction_timestamp, data_cutoff_at, model_version, "
                    "feature_version) "
                    "VALUES (:id, 'NVDA', :now, :now, 'm1', 'f1')"
                ),
                {"id": run_id, "now": T0},
            )
            trade_id = uuid.uuid4()
            await connection.execute(
                text(
                    "INSERT INTO simulated_trades "
                    "(id, forecast_run_id, symbol, side, decision_timestamp, planned_exit_horizon, "
                    "planned_exit_timestamp, strategy_version, config_hash, status, plan_hash) "
                    "VALUES (:id, :run, 'NVDA', 'NO_TRADE', :now, '1D', :now, 's1', "
                    "'c1', 'NO_TRADE', :hash)"
                ),
                {"id": trade_id, "run": run_id, "now": T0, "hash": uuid.uuid4().hex},
            )
            with pytest.raises(DBAPIError, match="immutable"):
                async with connection.begin_nested():
                    await connection.execute(
                        text("UPDATE simulated_trades SET status = 'CLOSED' WHERE id = :id"),
                        {"id": trade_id},
                    )
            with pytest.raises(DBAPIError, match="immutable"):
                async with connection.begin_nested():
                    await connection.execute(
                        text("DELETE FROM simulated_trades WHERE id = :id"), {"id": trade_id}
                    )
        finally:
            await transaction.rollback()


async def test_all_day7_append_only_tables_have_row_and_truncate_triggers(
    engine: AsyncEngine,
) -> None:
    async with engine.connect() as connection:
        rows = (
            (
                await connection.execute(
                    text(
                        "SELECT tgname FROM pg_trigger "
                        "WHERE NOT tgisinternal AND tgname LIKE 'trg_%_immutable_%'"
                    )
                )
            )
            .scalars()
            .all()
        )
    names = set(rows)
    for table in (
        "forecast_actuals",
        "forecast_evaluations",
        "simulated_trades",
        "simulated_trade_events",
        "paper_positions",
        "portfolio_snapshots",
    ):
        assert f"trg_{table}_immutable_row" in names
        assert f"trg_{table}_immutable_truncate" in names
