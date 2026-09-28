"""World Monitor adapter tests: pure, no network (httpx.MockTransport), no DB.

Payload shapes below follow the documented World Monitor API (NewsService OpenAPI ``NewsItem`` and
the MCP ``get_news_intelligence`` ``topStories`` schema). They are docs-derived, not live captures.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from typing import Any

import httpx
import pytest

from app.world.providers.base import WorldEventProvider
from app.world.providers.worldmonitor import (
    API_KEY_HEADER,
    DIGEST_PATH,
    WorldMonitorProvider,
    WorldProviderAuthError,
    WorldProviderUnavailable,
    WorldProviderUnconfigured,
    WorldRateLimited,
    extract_worldmonitor_items,
    map_worldmonitor_item,
    sanitize_text,
)
from app.world.types import WorldMode, WorldProviderName, WorldProviderState

KEY = "wm_0123456789abcdef0123456789abcdef01234567"
T0 = datetime(2026, 9, 16, 12, 0, tzinfo=UTC)
PUB = datetime(2026, 9, 16, 9, 0, tzinfo=UTC)
PUB_MS = int(PUB.timestamp() * 1000)


# ---- sample payloads (documented shapes) -------------------------------------------------
def digest_item(**over: Any) -> dict[str, Any]:
    """REST ``NewsItem`` (GET /api/news/v1/list-feed-digest)."""
    item: dict[str, Any] = {
        "source": "Reuters",
        "title": "Iran warns tankers over Strait of Hormuz transit",
        "link": "https://example.com/news/hormuz-1",
        "publishedAt": PUB_MS,
        "isAlert": True,
        "threat": {
            "level": "THREAT_LEVEL_HIGH",
            "category": "conflict",
            "confidence": 0.8,
            "source": "llm",
        },
        "location": {"latitude": 26.57, "longitude": 56.25},
        "locationName": "Strait of Hormuz",
        "importanceScore": 118,
        "corroborationCount": 6,
        "credibilityScore": 85,
        "snippet": "Shipping insurers raised war-risk premiums.",
        "tickers": ["XOM"],
    }
    item.update(over)
    return item


def top_story(**over: Any) -> dict[str, Any]:
    """MCP ``get_news_intelligence`` ``insights.topStories[]`` entry."""
    story: dict[str, Any] = {
        "primaryTitle": "TSMC halts fab lines after M7.2 quake off Hualien",
        "primarySource": "Bloomberg",
        "primaryLink": "https://example.com/news/tsmc-quake",
        "pubDate": "2026-09-16T09:00:00Z",
        "sourceCount": 5,
        "uniqueSourceCount": 4,
        "importanceScore": 90,
        "effectiveImportanceScore": 72,
        "credibilityScore": 90,
        "sources": ["Bloomberg", "Reuters", "AP"],
        "memberTitles": [
            "TSMC halts fab lines after M7.2 quake off Hualien",
            "Taiwan quake hits chips",
        ],
        "sourceTier": 1,
        "entityCorroboration": True,
        "corroborationSourceCount": 3,
        "category": "natural_disaster",
        "threatLevel": "critical",
        "countryCode": "TW",
        "isAlert": True,
        "sourceProvenance": {"risk": "low", "type": "wire"},
    }
    story.update(over)
    return story


def digest_payload(*items: dict[str, Any], bucket: str = "energy") -> dict[str, Any]:
    return {
        "categories": {bucket: {"items": list(items)}},
        "feedStatuses": {},
        "generatedAt": "2026-09-16T11:59:00Z",
    }


def mcp_payload(*stories: dict[str, Any]) -> dict[str, Any]:
    envelope = {
        "cached_at": "2026-09-16T11:30:00Z",
        "stale": False,
        "data": {"insights": {"topStories": list(stories)}},
    }
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {"content": [{"type": "text", "text": json.dumps(envelope)}]},
    }


# ---- harness -----------------------------------------------------------------------------
class FakeClock:
    def __init__(self, now: datetime = T0) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


class Upstream:
    """MockTransport handler recording every request; ``responder`` builds the response."""

    def __init__(self, responder: Any = None) -> None:
        self.requests: list[httpx.Request] = []
        self.responder = responder or (lambda req: httpx.Response(200, json=digest_payload()))

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.responder(request)


def make_provider(
    upstream: Upstream,
    *,
    api_key: str | None = KEY,
    clock: FakeClock | None = None,
    interval: float = 1800.0,
    **kw: Any,
) -> WorldMonitorProvider:
    return WorldMonitorProvider(
        api_key=api_key,
        base_url="https://wm.test",
        poll_interval_s=interval,
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(upstream)),
        clock=clock or FakeClock(),
        **kw,
    )


# ---- pure mapping ------------------------------------------------------------------------
def test_map_digest_item_full_fields() -> None:
    ev = map_worldmonitor_item(digest_item(), T0)
    assert ev is not None
    assert ev.provider == "world_monitor" and ev.is_replay is False
    assert ev.headline == "Iran warns tankers over Strait of Hormuz transit"
    assert ev.body == "Shipping insurers raised war-risk premiums."
    assert ev.occurred_at == PUB
    assert (ev.latitude, ev.longitude) == (26.57, 56.25)
    assert ev.entities == ["Strait of Hormuz"]
    assert ev.categories == ["conflict"]
    assert ev.provider_event_id and ev.provider_event_id.startswith("wm:")
    assert ev.provider_scores == {
        "importance": 1.0,  # 118 capped at 100 -> 1.0
        "credibility": 0.85,
        "unique_sources": 0.6,
        "threat_level": 0.8,
        "threat_confidence": 0.8,
    }
    (ref,) = ev.sources
    assert ref.provider == "world_monitor"
    assert ref.source_name == "Reuters"
    assert ref.source_url == "https://example.com/news/hormuz-1"
    assert ref.published_at == PUB and ref.retrieved_at == T0
    assert ref.reliability == pytest.approx(0.85)
    assert ref.metadata["tickers"] == ["XOM"]
    assert ref.metadata["retain_until"] == (T0 + timedelta(days=30)).isoformat()
    assert "raw" not in ref.metadata  # no full payload copy (30-day retention terms)


def test_map_top_story_shape_iso_pubdate() -> None:
    ev = map_worldmonitor_item(top_story(), T0)
    assert ev is not None
    assert ev.headline.startswith("TSMC halts fab lines")
    assert ev.occurred_at == PUB
    assert ev.country == "TW"
    assert ev.latitude is None and ev.longitude is None  # get_news_intelligence has no coordinates
    assert ev.categories == ["natural_disaster"]
    assert ev.provider_scores["importance"] == pytest.approx(0.72)  # effective score preferred
    assert ev.provider_scores["unique_sources"] == pytest.approx(0.4)
    assert ev.provider_scores["threat_level"] == 1.0
    ref = ev.sources[0]
    assert ref.source_name == "Bloomberg"
    assert ref.reliability == pytest.approx(0.9)
    assert ref.metadata["contributing_sources"] == ["Bloomberg", "Reuters", "AP"]
    assert ref.metadata["country_certainty"] == "low"  # countryCode is guessed from the headline


@pytest.mark.parametrize(
    "value",
    [
        PUB_MS,  # epoch ms
        PUB_MS // 1000,  # epoch seconds
        str(PUB_MS),  # numeric string
        "2026-09-16T09:00:00Z",  # ISO Z
        "2026-09-16T09:00:00+00:00",
        "2026-09-16T11:00:00+02:00",  # non-UTC offset
        "Wed, 16 Sep 2026 09:00:00 GMT",  # RFC 2822 (RSS)
    ],
)
def test_pubdate_formats_all_normalize_to_same_utc(value: Any) -> None:
    ev = map_worldmonitor_item(top_story(pubDate=value), T0)
    assert ev is not None and ev.occurred_at == PUB
    assert ev.sources[0].published_at == PUB


@pytest.mark.parametrize("value", [None, "", "not a date", 0, -5, True, 4e15, {"a": 1}])
def test_bad_or_missing_timestamp_falls_back_to_retrieved_at(value: Any) -> None:
    ev = map_worldmonitor_item(top_story(pubDate=value), T0)
    assert ev is not None
    assert ev.occurred_at == T0
    assert ev.sources[0].published_at is None
    assert ev.sources[0].metadata["published_at_missing"] is True


@pytest.mark.parametrize(
    "bad",
    [
        None,
        "string",
        42,
        [],
        {},
        {"title": "no source"},
        {"source": "Reuters"},
        {"source": "Reuters", "title": "   "},
        {"source": "  ", "title": "headline"},
        {"source": 5, "title": ["x"]},
    ],
)
def test_malformed_items_return_none(bad: Any) -> None:
    assert map_worldmonitor_item(bad, T0) is None


def test_mapper_never_raises_on_hostile_values() -> None:
    hostile = digest_item(
        importanceScore="NaN",
        credibilityScore=float("inf"),
        corroborationCount=[1],
        threat="oops",
        location={"latitude": "x", "longitude": 999},
        tickers="XOM",
        sources="Reuters",
        memberTitles={"a": 1},
        publishedAt=float("nan"),
        link="javascript:alert(1)",
        countryCode=12,
    )
    ev = map_worldmonitor_item(hostile, T0)
    assert ev is not None
    assert ev.sources[0].source_url is None  # non-http(s) link dropped
    assert ev.latitude is None and ev.longitude is None
    assert ev.country is None
    assert all(0.0 <= v <= 1.0 for v in ev.provider_scores.values())


def test_scores_clamped_and_unknown_threat_omitted() -> None:
    ev = map_worldmonitor_item(
        digest_item(
            importanceScore=-10,
            credibilityScore=250,
            corroborationCount=99,
            threat={"level": "THREAT_LEVEL_UNSPECIFIED", "confidence": 7},
        ),
        T0,
    )
    assert ev is not None
    assert ev.provider_scores["importance"] == 0.0
    assert ev.provider_scores["credibility"] == 1.0
    assert ev.provider_scores["unique_sources"] == 1.0
    assert "threat_level" not in ev.provider_scores
    assert ev.provider_scores["threat_confidence"] == 1.0


def test_invalid_lat_lon_pair_dropped() -> None:
    ev = map_worldmonitor_item(digest_item(location={"latitude": 95, "longitude": 10}), T0)
    assert ev is not None and ev.latitude is None and ev.longitude is None


def test_sanitize_strips_control_chars_and_caps_lengths() -> None:
    assert sanitize_text("a\x00b\x07c‮d\tE\n\nF", 100) == "abcd E F"
    long_headline = "H" * 900
    long_body = "B" * 9000
    ev = map_worldmonitor_item(digest_item(title=f"\x00{long_headline}", snippet=long_body), T0)
    assert ev is not None
    assert len(ev.headline) == 500
    assert ev.body is not None and len(ev.body) == 4000
    assert "\x00" not in ev.headline


def test_event_id_is_stable_and_id_field_wins() -> None:
    a = map_worldmonitor_item(digest_item(), T0)
    b = map_worldmonitor_item(digest_item(), T0 + timedelta(hours=1))
    assert a and b and a.provider_event_id == b.provider_event_id
    c = map_worldmonitor_item(digest_item(id="abc-123"), T0)
    assert c is not None and c.provider_event_id == "wm:abc-123"


def test_extract_items_shapes() -> None:
    assert (
        extract_worldmonitor_items(digest_payload(digest_item(), bucket="finance"))[0][  # type: ignore[index]
            "_category_bucket"
        ]
        == "finance"
    )
    assert (
        len(extract_worldmonitor_items({"data": {"insights": {"topStories": [top_story()]}}}) or [])
        == 1
    )
    assert len(extract_worldmonitor_items({"topStories": [top_story()]}) or []) == 1
    assert extract_worldmonitor_items({"categories": {}}) == []
    assert extract_worldmonitor_items({"unexpected": 1}) is None
    assert extract_worldmonitor_items("nope") is None


# ---- provider: unconfigured --------------------------------------------------------------
@pytest.mark.parametrize("key", [None, "", "   "])
async def test_unconfigured_makes_zero_requests(key: str | None) -> None:
    up = Upstream()
    p = make_provider(up, api_key=key)
    h = p.health()
    assert h.state == WorldProviderState.UNCONFIGURED
    assert h.configured is False and h.mode == WorldMode.OFFLINE
    assert h.provider == WorldProviderName.WORLD_MONITOR
    with pytest.raises(WorldProviderUnconfigured):
        await p.connect()
    with pytest.raises(WorldProviderUnconfigured):
        await p.fetch_recent()
    assert [e async for e in p.stream()] == []
    await p.disconnect()
    assert up.requests == []


def test_provider_satisfies_protocol_and_hides_key() -> None:
    p = make_provider(Upstream())
    assert isinstance(p, WorldEventProvider)
    assert KEY not in repr(p)
    assert p.min_interval_s == 1800.0


# ---- provider: healthy path --------------------------------------------------------------
async def test_fetch_recent_single_get_with_auth_header_and_timeout() -> None:
    up = Upstream(lambda _r: httpx.Response(200, json=digest_payload(digest_item())))
    p = make_provider(up)
    await p.connect()
    assert up.requests == []  # connect() itself does not poll
    assert p.health().state == WorldProviderState.CONNECTING
    events = await p.fetch_recent()
    assert len(events) == 1 and events[0].provider_scores["importance"] == 1.0
    (req,) = up.requests
    assert req.method == "GET" and req.url.path == DIGEST_PATH
    assert req.url.host == "wm.test"
    assert req.headers[API_KEY_HEADER] == KEY
    assert "authorization" not in req.headers
    assert req.headers["user-agent"].startswith("ECHO/")
    assert req.extensions["timeout"]["read"] == 20.0
    h = p.health()
    assert h.state == WorldProviderState.HEALTHY and h.mode == WorldMode.LIVE
    assert h.last_success_at == T0 and h.last_event_at == PUB
    assert h.events_received == 1 and h.last_error is None
    assert h.poll_interval_s == 1800.0
    await p.disconnect()


async def test_since_filters_by_occurred_at() -> None:
    up = Upstream(
        lambda _r: httpx.Response(
            200,
            json=digest_payload(
                digest_item(),
                digest_item(
                    title="Later item", link="https://example.com/2", publishedAt=PUB_MS + 60000
                ),
            ),
        )
    )
    p = make_provider(up)
    events = await p.fetch_recent(since=PUB)
    assert [e.headline for e in events] == ["Later item"]


async def test_same_story_in_two_buckets_merges_categories() -> None:
    payload = {
        "categories": {
            "energy": {"items": [digest_item(threat={"level": "THREAT_LEVEL_LOW"})]},
            "middleeast": {"items": [digest_item(threat={"level": "THREAT_LEVEL_LOW"})]},
        }
    }
    p = make_provider(Upstream(lambda _r: httpx.Response(200, json=payload)))
    (ev,) = await p.fetch_recent()
    assert ev.categories == ["energy", "middleeast"]


async def test_malformed_items_counted_not_raised() -> None:
    payload = digest_payload(
        digest_item(), {"title": "no source"}, "garbage", digest_item(link="x")
    )  # type: ignore[arg-type]
    p = make_provider(Upstream(lambda _r: httpx.Response(200, json=payload)))
    events = await p.fetch_recent()
    assert len(events) == 2  # valid item (link "x" dropped -> still valid, distinct id)
    h = p.health()
    assert h.malformed_events == 2 and h.state == WorldProviderState.HEALTHY


async def test_unusable_body_degrades_and_counts_malformed() -> None:
    for resp in (
        httpx.Response(200, text="<html>challenge</html>"),
        httpx.Response(200, json={"unexpected": True}),
    ):
        p = make_provider(Upstream(lambda _r, r=resp: r))
        with pytest.raises(WorldProviderUnavailable):
            await p.fetch_recent()
        h = p.health()
        assert h.state == WorldProviderState.DEGRADED and h.mode == WorldMode.OFFLINE
        assert h.malformed_events == 1


# ---- provider: errors --------------------------------------------------------------------
async def test_429_retry_after_sets_health_and_blocks_until_expiry() -> None:
    clock = FakeClock()
    up = Upstream(
        lambda _r: httpx.Response(429, headers={"Retry-After": "120"}, json={"error": "x"})
    )
    p = make_provider(up, clock=clock, interval=30.0)
    with pytest.raises(WorldRateLimited) as ei:
        await p.fetch_recent()
    assert ei.value.retry_after_s == 120.0
    h = p.health()
    assert h.state == WorldProviderState.DEGRADED and h.mode == WorldMode.OFFLINE
    assert h.retry_after_until == T0 + timedelta(seconds=120)
    assert h.last_error and KEY not in h.last_error
    assert len(up.requests) == 1
    clock.advance(60)  # still inside the Retry-After window: no new request
    with pytest.raises(WorldRateLimited) as ei2:
        await p.fetch_recent()
    assert ei2.value.retry_after_s == pytest.approx(60.0)
    assert len(up.requests) == 1
    clock.advance(61)  # window over: request is made again
    up.responder = lambda _r: httpx.Response(200, json=digest_payload(digest_item()))
    assert len(await p.fetch_recent()) == 1
    assert len(up.requests) == 2
    h = p.health()
    assert h.state == WorldProviderState.HEALTHY and h.retry_after_until is None


async def test_503_with_and_without_retry_after() -> None:
    up = Upstream(lambda _r: httpx.Response(503, headers={"Retry-After": "5"}))
    p = make_provider(up)
    with pytest.raises(WorldRateLimited) as ei:
        await p.fetch_recent()
    assert ei.value.retry_after_s == 5.0
    up2 = Upstream(lambda _r: httpx.Response(503))
    p2 = make_provider(up2)
    with pytest.raises(WorldRateLimited) as ei2:
        await p2.fetch_recent()
    assert ei2.value.retry_after_s == 60.0  # backoff floor when header absent


async def test_retry_after_http_date_supported() -> None:
    when = format_datetime(T0 + timedelta(seconds=90), usegmt=True)
    up = Upstream(lambda _r: httpx.Response(429, headers={"Retry-After": when}))
    p = make_provider(up)
    with pytest.raises(WorldRateLimited) as ei:
        await p.fetch_recent()
    assert ei.value.retry_after_s == pytest.approx(90.0)


@pytest.mark.parametrize("status", [401, 403])
async def test_auth_failure_is_error_state_with_redacted_message(status: int) -> None:
    up = Upstream(lambda _r: httpx.Response(status, json={"error": f"bad key {KEY}"}))
    p = make_provider(up)
    with pytest.raises(WorldProviderAuthError) as ei:
        await p.fetch_recent()
    h = p.health()
    assert h.state == WorldProviderState.ERROR and h.mode == WorldMode.OFFLINE
    assert h.last_error and str(status) in h.last_error
    assert KEY not in str(ei.value) and KEY not in h.last_error
    assert KEY not in h.model_dump_json()


async def test_network_error_degrades_and_never_leaks_key(caplog: pytest.LogCaptureFixture) -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"connection refused (key={KEY})", request=request)

    p = make_provider(Upstream(boom))
    with caplog.at_level(logging.DEBUG), pytest.raises(WorldProviderUnavailable) as ei:
        await p.fetch_recent()
    h = p.health()
    assert h.state == WorldProviderState.DEGRADED and h.mode == WorldMode.OFFLINE
    assert KEY not in str(ei.value)
    assert h.last_error and KEY not in h.last_error and "ConnectError" in h.last_error
    assert KEY not in caplog.text
    assert KEY not in repr(p) and KEY not in h.model_dump_json()


async def test_timeout_is_degraded() -> None:
    def slow(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    p = make_provider(Upstream(slow))
    with pytest.raises(WorldProviderUnavailable):
        await p.fetch_recent()
    assert p.health().state == WorldProviderState.DEGRADED


async def test_server_error_500_degraded() -> None:
    p = make_provider(Upstream(lambda _r: httpx.Response(500)))
    with pytest.raises(WorldProviderUnavailable):
        await p.fetch_recent()
    assert p.health().state == WorldProviderState.DEGRADED


# ---- provider: interval / cache ----------------------------------------------------------
async def test_never_requests_sooner_than_interval_and_serves_cache() -> None:
    clock = FakeClock()
    up = Upstream(lambda _r: httpx.Response(200, json=digest_payload(digest_item())))
    p = make_provider(up, clock=clock, interval=600.0)
    first = await p.fetch_recent()
    clock.advance(599)
    second = await p.fetch_recent()
    assert len(up.requests) == 1
    assert [e.provider_event_id for e in first] == [e.provider_event_id for e in second]
    assert p.health().events_received == 1  # cache hits do not count as newly received
    clock.advance(2)
    await p.fetch_recent()
    assert len(up.requests) == 2


async def test_failed_poll_is_not_retried_before_interval() -> None:
    clock = FakeClock()
    up = Upstream(lambda _r: httpx.Response(500))
    p = make_provider(up, clock=clock, interval=600.0)
    with pytest.raises(WorldProviderUnavailable):
        await p.fetch_recent()
    clock.advance(10)
    assert await p.fetch_recent() == []
    assert len(up.requests) == 1


async def test_health_becomes_stale_when_no_success_for_three_intervals() -> None:
    clock = FakeClock()
    p = make_provider(Upstream(), clock=clock, interval=100.0)
    await p.fetch_recent()
    assert p.health().state == WorldProviderState.HEALTHY
    clock.advance(301)
    h = p.health()
    assert h.state == WorldProviderState.STALE and h.mode == WorldMode.OFFLINE


# ---- provider: stream + dedupe -----------------------------------------------------------
async def test_stream_dedupes_across_polls_and_honors_interval() -> None:
    clock = FakeClock()
    a = digest_item()
    b = digest_item(title="Second story", link="https://example.com/2", publishedAt=PUB_MS + 1000)
    bodies = [digest_payload(a), digest_payload(a, b), digest_payload(a, b)]
    up = Upstream(lambda _r: httpx.Response(200, json=bodies[min(len(up.requests) - 1, 2)]))
    sleeps: list[float] = []
    holder: dict[str, WorldMonitorProvider] = {}

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        clock.advance(seconds)
        if len(sleeps) >= 3:
            await holder["p"].disconnect()

    p = make_provider(up, clock=clock, interval=900.0, sleep=fake_sleep)
    holder["p"] = p
    got = [e.headline async for e in p.stream()]
    assert got == [a["title"], "Second story"]  # each event exactly once
    assert len(up.requests) == 3
    assert sleeps == [900.0, 900.0, 900.0]


async def test_stream_absorbs_errors_and_waits_for_retry_after() -> None:
    clock = FakeClock()
    responses = [
        httpx.Response(429, headers={"Retry-After": "3600"}),
        httpx.Response(200, json=digest_payload(digest_item())),
    ]
    up = Upstream(lambda _r: responses[len(up.requests) - 1])
    sleeps: list[float] = []
    holder: dict[str, WorldMonitorProvider] = {}

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        clock.advance(seconds)
        if len(sleeps) >= 2:
            await holder["p"].disconnect()

    p = make_provider(up, clock=clock, interval=600.0, sleep=fake_sleep)
    holder["p"] = p
    got = [e async for e in p.stream()]
    assert len(got) == 1
    assert sleeps[0] == 3600.0  # waited out Retry-After, not just the poll interval
    assert len(up.requests) == 2


async def test_stream_lru_is_bounded() -> None:
    p = make_provider(Upstream(), dedupe_size=2)
    assert [p._remember(i) for i in ("a", "b", "c")] == [True, True, True]
    assert p._remember("a") is True  # evicted -> new again
    assert p._remember("c") is False


async def test_disconnect_ends_stream_without_sleeping_full_interval() -> None:
    import asyncio

    up = Upstream(lambda _r: httpx.Response(200, json=digest_payload(digest_item())))
    p = make_provider(up, interval=3600.0)  # default interruptible wait

    async def consume() -> list[str]:
        return [e.headline async for e in p.stream()]

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.05)
    await p.disconnect()
    got = await asyncio.wait_for(task, timeout=2.0)
    assert len(got) == 1


# ---- provider: MCP transport -------------------------------------------------------------
async def test_mcp_mode_posts_tools_call_and_maps_top_stories() -> None:
    up = Upstream(lambda _r: httpx.Response(200, json=mcp_payload(top_story())))
    p = make_provider(up, mode="mcp", mcp_url="https://wm.test/mcp")
    events = await p.fetch_recent()
    assert len(events) == 1 and events[0].country == "TW"
    (req,) = up.requests
    assert req.method == "POST" and req.url.path == "/mcp"
    assert req.headers[API_KEY_HEADER] == KEY
    body = json.loads(req.content)
    assert body["method"] == "tools/call" and body["params"]["name"] == "get_news_intelligence"
    assert p.health().state == WorldProviderState.HEALTHY


async def test_mcp_mode_parses_sse_reply() -> None:
    sse = "event: message\ndata: " + json.dumps(mcp_payload(top_story())) + "\n\n"
    up = Upstream(
        lambda _r: httpx.Response(200, text=sse, headers={"content-type": "text/event-stream"})
    )
    p = make_provider(up, mode="mcp")
    assert len(await p.fetch_recent()) == 1


async def test_mcp_jsonrpc_32029_on_http_200_is_rate_limited() -> None:
    err = {
        "jsonrpc": "2.0",
        "id": 1,
        "error": {"code": -32029, "message": "Rate limit exceeded. Max 60 requests per minute."},
    }
    clock = FakeClock()
    up = Upstream(lambda _r: httpx.Response(200, json=err))
    p = make_provider(up, mode="mcp", clock=clock, interval=30.0)
    with pytest.raises(WorldRateLimited) as ei:
        await p.fetch_recent()
    assert ei.value.retry_after_s == 60.0  # backoff floor without Retry-After header
    h = p.health()
    assert h.state == WorldProviderState.DEGRADED and h.retry_after_until == T0 + timedelta(
        seconds=60
    )
    with pytest.raises(WorldRateLimited):
        await p.fetch_recent()
    assert len(up.requests) == 1

    up2 = Upstream(lambda _r: httpx.Response(200, json=err, headers={"Retry-After": "7"}))
    p2 = make_provider(up2, mode="mcp")
    with pytest.raises(WorldRateLimited) as ei2:
        await p2.fetch_recent()
    assert ei2.value.retry_after_s == 7.0


async def test_mcp_jsonrpc_auth_error_is_error_state() -> None:
    err = {"jsonrpc": "2.0", "id": 1, "error": {"code": -32001, "message": f"auth {KEY}"}}
    p = make_provider(Upstream(lambda _r: httpx.Response(200, json=err)), mode="mcp")
    with pytest.raises(WorldProviderAuthError) as ei:
        await p.fetch_recent()
    assert p.health().state == WorldProviderState.ERROR
    assert KEY not in str(ei.value) and KEY not in (p.health().last_error or "")


def test_invalid_mode_rejected() -> None:
    with pytest.raises(ValueError):
        WorldMonitorProvider(api_key=KEY, mode="soap")
    with pytest.raises(ValueError):
        WorldMonitorProvider(api_key=KEY, poll_interval_s=0)
