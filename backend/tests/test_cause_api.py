import httpx


async def test_missing_market_shock_returns_not_found(
    client: httpx.AsyncClient,
) -> None:
    response = await client.post(
        "/api/v1/investigations/market-shock/evt_missing_cause",
        params={"data_cutoff_at": "2026-09-20T18:00:00Z"},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


async def test_cluster_endpoint_is_empty_without_market_events(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get(
        "/api/v1/market/clusters",
        params={"data_cutoff_at": "2026-09-20T18:00:00Z"},
    )

    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0}


async def test_cause_endpoints_require_aware_cutoffs(
    client: httpx.AsyncClient,
) -> None:
    response = await client.post(
        "/api/v1/investigations/market-shock/evt_missing_cause",
        params={"data_cutoff_at": "2026-09-20T18:00:00"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
