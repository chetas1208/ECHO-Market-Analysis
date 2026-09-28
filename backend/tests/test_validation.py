import httpx
import pytest

from tests.conftest import event_payload


def assert_validation_envelope(resp: httpx.Response, field: str) -> dict:
    assert resp.status_code == 422, resp.text
    body = resp.json()
    error = body["error"]
    assert error["code"] == "validation_error"
    assert error["request_id"] == resp.headers["x-request-id"]
    locs = [tuple(d["loc"]) for d in error["details"]]
    assert ("body", field) in locs, locs
    assert "Traceback" not in resp.text
    return error


@pytest.mark.parametrize("field", ["severity", "novelty", "corroboration", "confidence"])
@pytest.mark.parametrize("value", [-0.01, 1.01, 5, "high"])
async def test_unit_interval_fields_rejected(
    client: httpx.AsyncClient, field: str, value: object
) -> None:
    resp = await client.post("/api/v1/events", json=event_payload(**{field: value}))
    assert_validation_envelope(resp, field)


@pytest.mark.parametrize("value", [0, 1, 0.0, 1.0])
async def test_unit_interval_boundaries_accepted(client: httpx.AsyncClient, value: float) -> None:
    resp = await client.post(
        "/api/v1/events",
        json=event_payload(severity=value, novelty=value, corroboration=value, confidence=value),
    )
    assert resp.status_code == 201


@pytest.mark.parametrize("timestamp", ["2026-09-20T17:00:00", "2026-09-20 17:00:00"])
async def test_naive_timestamp_rejected_with_clear_message(
    client: httpx.AsyncClient, timestamp: str
) -> None:
    resp = await client.post("/api/v1/events", json=event_payload(timestamp=timestamp))
    error = assert_validation_envelope(resp, "timestamp")
    messages = " ".join(d["msg"] for d in error["details"])
    assert "timezone" in messages


async def test_missing_and_garbage_timestamp_rejected(client: httpx.AsyncClient) -> None:
    payload = event_payload()
    del payload["timestamp"]
    assert_validation_envelope(await client.post("/api/v1/events", json=payload), "timestamp")
    resp = await client.post("/api/v1/events", json=event_payload(timestamp="yesterday"))
    assert_validation_envelope(resp, "timestamp")


@pytest.mark.parametrize("title", ["", "   "])
async def test_empty_title_rejected(client: httpx.AsyncClient, title: str) -> None:
    assert_validation_envelope(
        await client.post("/api/v1/events", json=event_payload(title=title)), "title"
    )


@pytest.mark.parametrize(
    "event_id", ["mock_1", "EVT_upper", "evt_", "evt_has-dash", "evt_" + "a" * 65, "evt_sp ace"]
)
async def test_bad_client_id_rejected(client: httpx.AsyncClient, event_id: str) -> None:
    assert_validation_envelope(
        await client.post("/api/v1/events", json=event_payload(id=event_id)), "id"
    )


async def test_client_id_max_length_accepted(client: httpx.AsyncClient) -> None:
    resp = await client.post("/api/v1/events", json=event_payload(id="evt_" + "a" * 64))
    assert resp.status_code == 201


@pytest.mark.parametrize("value", [1.01, -1.5, "big"])
async def test_economic_channel_out_of_range_rejected(
    client: httpx.AsyncClient, value: object
) -> None:
    resp = await client.post(
        "/api/v1/events", json=event_payload(economic_channels={"oil_supply": value})
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_error"


async def test_economic_channel_bounds_accepted(client: httpx.AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/events", json=event_payload(economic_channels={"a": -1, "b": 1, "c": 0})
    )
    assert resp.status_code == 201


async def test_invalid_source_type_rejected(client: httpx.AsyncClient) -> None:
    resp = await client.post("/api/v1/events", json=event_payload(source_type="rumor"))
    assert_validation_envelope(resp, "source_type")


async def test_unknown_fields_rejected(client: httpx.AsyncClient) -> None:
    resp = await client.post("/api/v1/events", json=event_payload(sevrity=0.4))
    assert_validation_envelope(resp, "sevrity")


async def test_malformed_json_returns_validation_envelope(client: httpx.AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/events", content=b"{not json", headers={"content-type": "application/json"}
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_error"


async def test_validation_error_does_not_echo_input(client: httpx.AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/events", json=event_payload(title="", summary="SECRET-PAYLOAD-TEXT")
    )
    assert resp.status_code == 422
    assert "SECRET-PAYLOAD-TEXT" not in resp.text
