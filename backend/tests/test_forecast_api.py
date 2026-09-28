import httpx


async def test_missing_forecast_event_returns_not_found(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/api/v1/forecasts/preview",
        json={"event_id": "evt_missing_forecast", "symbol": "NVDA"},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


async def test_forecasting_status_is_explicit_when_artifact_is_missing(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get("/api/v1/forecasting/status")
    assert response.status_code == 200
    body = response.json()
    assert body["model_status"] in {"READY", "FORECAST_UNAVAILABLE"}
    assert "chronos_status" in body
