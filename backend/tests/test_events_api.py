from datetime import UTC, datetime, timedelta

import httpx
import pytest

from tests.conftest import event_payload, unique_event_id

EVENT_FIELDS = {
    "id",
    "timestamp",
    "source_type",
    "event_type",
    "title",
    "summary",
    "entities",
    "companies",
    "locations",
    "economic_channels",
    "severity",
    "novelty",
    "corroboration",
    "confidence",
    "source_refs",
    "metadata",
    "is_mock",
    "created_at",
    "ingested_at",
    "revision",
    "updated_at",
    "source_count",
    "independent_source_count",
}


async def test_create_event_with_client_id_and_fetch(client: httpx.AsyncClient) -> None:
    event_id = unique_event_id()
    payload = event_payload(
        id=event_id,
        source_type="world",
        summary="Something happened",
        entities=["Strait of Hormuz"],
        companies=["XOM"],
        locations=["Middle East"],
        economic_channels={"oil_supply": -0.82, "shipping_costs": 0.77},
        source_refs=[{"name": "fixture", "url": None}],
        metadata={"k": "v"},
        is_mock=True,
    )
    created = await client.post("/api/v1/events", json=payload)
    assert created.status_code == 201, created.text
    body = created.json()
    assert set(body) == EVENT_FIELDS
    assert body["id"] == event_id
    assert body["source_type"] == "world"
    assert body["timestamp"] == "2026-09-20T17:00:00Z"
    assert body["economic_channels"] == {"oil_supply": -0.82, "shipping_costs": 0.77}
    assert body["severity"] == 0.5 and isinstance(body["severity"], float)
    assert body["is_mock"] is True
    assert body["metadata"] == {"k": "v"}
    assert body["source_refs"] == [{"name": "fixture", "url": None}]
    assert body["created_at"].endswith("Z") and body["ingested_at"].endswith("Z")

    fetched = await client.get(f"/api/v1/events/{event_id}")
    assert fetched.status_code == 200
    assert fetched.json() == body


async def test_create_event_generates_id_and_defaults(client: httpx.AsyncClient) -> None:
    resp = await client.post("/api/v1/events", json=event_payload())
    assert resp.status_code == 201
    body = resp.json()
    assert body["id"].startswith("evt_") and len(body["id"]) == 16
    assert body["entities"] == [] and body["companies"] == [] and body["locations"] == []
    assert body["economic_channels"] == {} and body["source_refs"] == []
    assert body["metadata"] == {} and body["summary"] is None and body["is_mock"] is False


async def test_offset_timestamp_is_normalized_to_utc(client: httpx.AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/events", json=event_payload(timestamp="2026-09-20T13:00:00-04:00")
    )
    assert resp.status_code == 201
    assert resp.json()["timestamp"] == "2026-09-20T17:00:00Z"


@pytest.mark.parametrize("source_type", ["world", "market", "financial", "WORLD"])
async def test_source_types_accepted_and_returned_lowercase(
    client: httpx.AsyncClient, source_type: str
) -> None:
    resp = await client.post("/api/v1/events", json=event_payload(source_type=source_type))
    assert resp.status_code == 201
    assert resp.json()["source_type"] == source_type.lower()


async def test_duplicate_id_returns_409_conflict(client: httpx.AsyncClient) -> None:
    payload = event_payload(id=unique_event_id())
    assert (await client.post("/api/v1/events", json=payload)).status_code == 201
    dup = await client.post("/api/v1/events", json={**payload, "title": "Different"})
    assert dup.status_code == 409
    error = dup.json()["error"]
    assert error["code"] == "conflict"
    assert error["request_id"] == dup.headers["x-request-id"]
    # original untouched
    fetched = await client.get(f"/api/v1/events/{payload['id']}")
    assert fetched.json()["title"] == "Test event"


async def test_get_missing_event_returns_404_envelope(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/v1/events/evt_does_not_exist")
    assert resp.status_code == 404
    error = resp.json()["error"]
    assert set(error) >= {"code", "message", "request_id"}
    assert error["code"] == "not_found"


async def test_list_orders_newest_first_with_id_tiebreak_and_paginates(
    client: httpx.AsyncClient,
) -> None:
    base = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)
    specs = [
        ("evt_list_a", base + timedelta(hours=1)),
        ("evt_list_b", base + timedelta(hours=3)),
        ("evt_list_c", base + timedelta(hours=2)),
        ("evt_list_d", base + timedelta(hours=3)),  # ties with b -> id ascending
        ("evt_list_e", base),
    ]
    for event_id, ts in specs:
        resp = await client.post(
            "/api/v1/events", json=event_payload(id=event_id, timestamp=ts.isoformat())
        )
        assert resp.status_code == 201

    full = await client.get("/api/v1/events")
    assert full.status_code == 200
    body = full.json()
    assert set(body) == {"items", "total", "limit", "offset"}
    assert body["total"] == 5 and body["limit"] == 50 and body["offset"] == 0
    assert [e["id"] for e in body["items"]] == [
        "evt_list_b",
        "evt_list_d",
        "evt_list_c",
        "evt_list_a",
        "evt_list_e",
    ]

    page1 = (await client.get("/api/v1/events", params={"limit": 2, "offset": 0})).json()
    page2 = (await client.get("/api/v1/events", params={"limit": 2, "offset": 2})).json()
    page3 = (await client.get("/api/v1/events", params={"limit": 2, "offset": 4})).json()
    assert [e["id"] for e in page1["items"]] == ["evt_list_b", "evt_list_d"]
    assert [e["id"] for e in page2["items"]] == ["evt_list_c", "evt_list_a"]
    assert [e["id"] for e in page3["items"]] == ["evt_list_e"]
    assert page1["total"] == page2["total"] == page3["total"] == 5
    assert page2["limit"] == 2 and page2["offset"] == 2


async def test_list_empty(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/v1/events")
    assert resp.json() == {"items": [], "total": 0, "limit": 50, "offset": 0}


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 201}, {"offset": -1}, {"limit": "abc"}])
async def test_list_rejects_bad_pagination(client: httpx.AsyncClient, params: dict) -> None:
    resp = await client.get("/api/v1/events", params=params)
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_error"


async def test_limit_bounds_accepted(client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/v1/events", params={"limit": 1})).status_code == 200
    assert (await client.get("/api/v1/events", params={"limit": 200})).status_code == 200


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("PUT", "/api/v1/events/evt_x"),
        ("PATCH", "/api/v1/events/evt_x"),
        ("DELETE", "/api/v1/events/evt_x"),
        ("PUT", "/api/v1/events"),
        ("PATCH", "/api/v1/events"),
        ("DELETE", "/api/v1/events"),
        ("POST", "/api/v1/events/evt_x"),
    ],
)
async def test_no_event_mutation_routes(client: httpx.AsyncClient, method: str, path: str) -> None:
    resp = await client.request(method, path, json={})
    assert resp.status_code in (404, 405)
    assert "error" in resp.json()


@pytest.mark.parametrize("method", ["PUT", "PATCH", "DELETE", "GET"])
@pytest.mark.parametrize("path", ["/api/v1/forecast_runs", "/api/v1/forecast-runs/x"])
async def test_no_forecast_endpoints(client: httpx.AsyncClient, method: str, path: str) -> None:
    resp = await client.request(method, path)
    assert resp.status_code in (404, 405)
    assert resp.json()["error"]["code"] in ("not_found", "method_not_allowed")


async def test_openapi_exposes_no_mutating_routes_except_event_post(
    client: httpx.AsyncClient,
) -> None:
    spec = (await client.get("/openapi.json")).json()
    mutating = {
        (path, method)
        for path, ops in spec["paths"].items()
        for method in ops
        if method in {"post", "put", "patch", "delete"}
    }
    assert mutating == {
        ("/api/v1/events", "post"),
        ("/api/v1/investigations/market-shock/{event_id}", "post"),
        ("/api/v1/forecasts/preview", "post"),
        ("/api/v1/forecasts", "post"),
            ("/api/v1/forecasts/{forecast_id}/actuals", "post"),
            ("/api/v1/forecasts/{forecast_id}/simulate", "post"),
            ("/api/v1/backtests", "post"),
            ("/api/v1/paper/execute/{decision_id}", "post"),
            ("/api/v1/execution/reconcile", "post"),
        }
