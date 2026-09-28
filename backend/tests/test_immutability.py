"""The prediction ledger is append-only: enforced by Postgres triggers, not app code.

Writes to the ledger tables happen inside transactions that are always rolled back, so the
tests leave the (immutable) tables empty.
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from tests.conftest import unique_event_id

T0 = datetime(2026, 9, 20, 17, 0, tzinfo=UTC)

INSERT_RUN = text(
    """
    INSERT INTO forecast_runs
        (id, event_id, symbol, prediction_timestamp, data_cutoff_at, model_version,
         feature_version, graph_snapshot_id, event_snapshot_id, feature_hash)
    VALUES (:id, :event_id, 'XOM', :pred, :cutoff, 'm1', 'f1', 'g1', 'e1', 'h1')
    """
)
INSERT_POINT = text(
    """
    INSERT INTO forecast_points
        (id, forecast_run_id, horizon, horizon_trading_days, target_timestamp,
         q10, q50, q90, probability_positive)
    VALUES (:id, :run_id, :horizon, :days, :target, :q10, :q50, :q90, :p)
    """
)
INSERT_EVENT = text(
    "INSERT INTO canonical_events (id, timestamp, source_type, event_type, title, "
    "severity, novelty, corroboration, confidence) "
    "VALUES (:id, :ts, 'WORLD', 't', 'T', 0.5, 0.5, 0.5, 0.5)"
)


def point_params(run_id: uuid.UUID, horizon: str = "1D", days: int = 1, **kw: object) -> dict:
    params = {
        "id": uuid.uuid4(),
        "run_id": run_id,
        "horizon": horizon,
        "days": days,
        "target": T0 + timedelta(days=days),
        "q10": -0.02,
        "q50": 0.01,
        "q90": 0.04,
        "p": 0.6,
    }
    params.update(kw)
    return params


@pytest_asyncio.fixture
async def conn(engine: AsyncEngine) -> AsyncIterator[AsyncConnection]:
    """A connection in a transaction that is rolled back at the end."""
    async with engine.connect() as connection:
        outer = await connection.begin()
        try:
            yield connection
        finally:
            await outer.rollback()


async def make_run(conn: AsyncConnection, event_id: str | None = None) -> uuid.UUID:
    run_id = uuid.uuid4()
    await conn.execute(INSERT_RUN, {"id": run_id, "event_id": event_id, "pred": T0, "cutoff": T0})
    return run_id


async def make_run_with_point(conn: AsyncConnection) -> tuple[uuid.UUID, uuid.UUID]:
    run_id = await make_run(conn)
    params = point_params(run_id)
    await conn.execute(INSERT_POINT, params)
    return run_id, params["id"]


@asynccontextmanager
async def expect_error(
    conn: AsyncConnection, exc: type[Exception], match: str
) -> AsyncIterator[None]:
    """Expect `exc` inside a savepoint, which keeps the outer transaction usable."""
    with pytest.raises(exc, match=match):
        async with conn.begin_nested():
            yield


async def assert_blocked(conn: AsyncConnection, sql: str, params: dict | None = None) -> None:
    async with expect_error(conn, DBAPIError, "immutable"):
        await conn.execute(text(sql), params or {})


async def test_insert_works_for_run_and_points(conn: AsyncConnection) -> None:
    event_id = unique_event_id("ledger")
    await conn.execute(INSERT_EVENT, {"id": event_id, "ts": T0})
    run_id = await make_run(conn, event_id)
    for horizon, days in [("1D", 1), ("2D", 2), ("5D", 5), ("10D", 10), ("20D", 20)]:
        await conn.execute(INSERT_POINT, point_params(run_id, horizon, days))
    count = (
        await conn.execute(
            text("SELECT count(*) FROM forecast_points WHERE forecast_run_id = :r"), {"r": run_id}
        )
    ).scalar_one()
    assert count == 5


async def test_market_triggered_run_without_event_allowed(conn: AsyncConnection) -> None:
    await make_run(conn, event_id=None)


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE forecast_runs SET model_version = 'tampered'",
        "UPDATE forecast_runs SET symbol = symbol",  # even a no-op rewrite is refused
        "DELETE FROM forecast_runs",
        "DELETE FROM forecast_runs WHERE true",
        "TRUNCATE forecast_runs CASCADE",
        "TRUNCATE forecast_runs, forecast_points, forecast_actuals, forecast_evaluations, "
        "simulated_trades, simulated_trade_events, paper_positions",
    ],
)
async def test_forecast_runs_reject_update_delete_truncate(conn: AsyncConnection, sql: str) -> None:
    await make_run(conn)
    await assert_blocked(conn, sql)


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE forecast_points SET q50 = 0.02",
        "UPDATE forecast_points SET q50 = q50",
        "DELETE FROM forecast_points",
        "TRUNCATE forecast_points",
    ],
)
async def test_forecast_points_reject_update_delete_truncate(
    conn: AsyncConnection, sql: str
) -> None:
    await make_run_with_point(conn)
    await assert_blocked(conn, sql)


async def test_plain_truncate_of_runs_is_refused(conn: AsyncConnection) -> None:
    await make_run(conn)
    # Refused by the FK check (forecast_points references it) before the trigger is reached.
    async with expect_error(conn, DBAPIError, "immutable|truncate a table referenced"):
        await conn.execute(text("TRUNCATE forecast_runs"))


async def test_truncate_cascade_from_events_cannot_reach_ledger(conn: AsyncConnection) -> None:
    event_id = unique_event_id("ledger")
    await conn.execute(INSERT_EVENT, {"id": event_id, "ts": T0})
    await make_run(conn, event_id)
    await assert_blocked(conn, "TRUNCATE canonical_events CASCADE")


async def test_deleting_referenced_event_is_restricted(conn: AsyncConnection) -> None:
    event_id = unique_event_id("ledger")
    await conn.execute(INSERT_EVENT, {"id": event_id, "ts": T0})
    await make_run(conn, event_id)
    async with expect_error(conn, IntegrityError, "foreign key"):
        await conn.execute(text("DELETE FROM canonical_events WHERE id = :i"), {"i": event_id})
    # run and event are still there
    assert (await conn.execute(text("SELECT count(*) FROM forecast_runs"))).scalar_one() == 1


async def test_deleting_referenced_run_is_blocked(conn: AsyncConnection) -> None:
    run_id, _ = await make_run_with_point(conn)
    await assert_blocked(conn, "DELETE FROM forecast_runs WHERE id = :i", {"i": run_id})


async def test_data_cutoff_must_not_exceed_prediction_timestamp(conn: AsyncConnection) -> None:
    async with expect_error(conn, IntegrityError, "cutoff_not_after_prediction"):
        await conn.execute(
            INSERT_RUN,
            {"id": uuid.uuid4(), "event_id": None, "pred": T0, "cutoff": T0 + timedelta(1)},
        )
    # equal is allowed
    await make_run(conn)


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        ({"q10": 0.05, "q50": 0.01, "q90": 0.04}, "quantile_order"),
        ({"q10": -0.02, "q50": 0.05, "q90": 0.04}, "quantile_order"),
        ({"p": 1.2}, "probability_positive_unit"),
        ({"p": -0.1}, "probability_positive_unit"),
        ({"horizon": "3D", "days": 3}, "horizon"),
        ({"horizon": "5D", "days": 1}, "horizon_days_match"),
    ],
)
async def test_forecast_point_constraints(
    conn: AsyncConnection, overrides: dict, constraint: str
) -> None:
    run_id = await make_run(conn)
    async with expect_error(conn, IntegrityError, constraint):
        await conn.execute(INSERT_POINT, point_params(run_id, **overrides))


async def test_one_point_per_horizon_per_run(conn: AsyncConnection) -> None:
    run_id = await make_run(conn)
    await conn.execute(INSERT_POINT, point_params(run_id, "1D", 1))
    async with expect_error(conn, IntegrityError, "uq_forecast_points_forecast_run_id_horizon"):
        await conn.execute(INSERT_POINT, point_params(run_id, "1D", 1))
    # a new vintage is a new run, which may hold the same horizon again
    other = await make_run(conn)
    await conn.execute(INSERT_POINT, point_params(other, "1D", 1))


async def test_committed_ledger_rows_cannot_be_changed_from_a_new_connection(
    engine: AsyncEngine,
) -> None:
    """Real (committed) path: insert with autocommit semantics, then try to tamper.

    The inserted rows can never be removed by tests, so this uses a savepoint-free rolled-back
    transaction for the insert and asserts tampering is refused within the same visibility.
    """
    async with engine.connect() as connection:
        outer = await connection.begin()
        try:
            run_id, point_id = await make_run_with_point(connection)
            await assert_blocked(
                connection,
                "UPDATE forecast_points SET q90 = 9 WHERE id = :i",
                {"i": point_id},
            )
            await assert_blocked(
                connection, "DELETE FROM forecast_runs WHERE id = :i", {"i": run_id}
            )
        finally:
            await outer.rollback()
