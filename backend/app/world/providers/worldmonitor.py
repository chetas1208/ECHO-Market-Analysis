"""World Monitor world-event adapter (plain ``httpx`` against the documented API surface).

Licensing: World Monitor is AGPL-3.0 (its ``sdk/`` and ``cli/`` are MIT). This module imports NO
World Monitor source and only calls the public network API; field names were read from the
documented OpenAPI (``docs/api/NewsService.openapi.yaml``) and MCP registry docs.

Documented surface used (``.reference-repos/worldmonitor`` @ 977161b)
- Base URL ``https://api.worldmonitor.app`` (``docs/api/worldmonitor.openapi.yaml`` ``servers``).
- ``GET /api/news/v1/list-feed-digest?variant=full`` returns
  ``{"categories": {<name>: {"items": [NewsItem]}}, "feedStatuses", "generatedAt", "coverage"}``.
  ``NewsItem``: ``source``, ``title``, ``link``, ``publishedAt`` (epoch ms), ``isAlert``,
  ``threat{level,category,confidence,source}``, ``location{latitude,longitude}``,
  ``locationName``, ``importanceScore`` (int; base 0-100 but reaches ~138 after boosts),
  ``corroborationCount``, ``storyMeta{sourceCount,...}``, ``snippet`` (<=400 chars),
  ``tickers[]``, ``credibilityScore`` (0-100).
- MCP tool ``get_news_intelligence`` (``POST https://worldmonitor.app/mcp``, JSON-RPC
  ``tools/call``) returns ``topStories[]``: ``primaryTitle``, ``primarySource``, ``primaryLink``,
  ``pubDate`` (epoch ms or ISO), ``importanceScore``/``effectiveImportanceScore``,
  ``credibilityScore`` (0-100), ``uniqueSourceCount``, ``sourceCount``,
  ``corroborationSourceCount``, ``sources[]``, ``memberTitles[]``, ``sourceTier``, ``category``,
  ``threatLevel``, ``countryCode``, ``isAlert``. The mapper accepts both shapes.
- Auth: header ``X-WorldMonitor-Key: wm_...`` (alias ``X-Api-Key``), NOT a Bearer token.
  401 = missing/invalid key; 403 = subscription inactive.
- Limits (``docs/usage-rate-limits.mdx``, ``docs/mcp-error-catalog.mdx``): default 600 req/min/IP;
  MCP 60/min per user and 50 quota-consuming calls per UTC day on Pro. 429 carries
  ``Retry-After`` in delta-seconds (daily cap: seconds until 00:00 UTC); 503 carries
  ``Retry-After`` (1-60 s). MCP per-minute limiter answers HTTP 200 + JSON-RPC error -32029.

Provider signals -> ``RawWorldEvent.provider_scores`` (all in [0, 1], heuristic, not probabilities):
- ``importance``       = min(importanceScore, 100) / 100 (effectiveImportanceScore preferred)
- ``credibility``      = clamp(credibilityScore / 100); also ``SourceRef.reliability``
- ``unique_sources``   = min(n, 10) / 10, n = uniqueSourceCount | corroborationCount |
  storyMeta.sourceCount | sourceCount (first present)
- ``threat_level``     = low 0.25, moderate/medium 0.5, elevated 0.65, high 0.8, critical 1.0
  (``THREAT_LEVEL_*`` prefix accepted; unspecified/unknown omitted)
- ``threat_confidence`` = threat.confidence (already 0..1)

Transports (``mode``): ``"rest"`` (default) = one ``GET {base_url}/api/news/v1/list-feed-digest``;
``"mcp"`` = ``POST {mcp_url}`` JSON-RPC ``tools/call get_news_intelligence`` (JSON or SSE reply;
-32029 = ``WorldRateLimited``; -32001/-32002 = auth error).
``countryCode`` is guessed by World Monitor from the headline: kept but flagged
``country_certainty="low"`` in ``SourceRef.metadata``. Data terms (EULA R3) allow retaining
headline data for 30 days only, so no full raw payload is copied and
``SourceRef.metadata["retain_until"]`` marks the purge date.

Secrets: the API key is only placed in the request header. It is redacted from every error
string, never logged, and hidden from ``repr``. External text is untrusted: control/bidi
characters are stripped and lengths capped (headline 500, body 4000).
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import math
import re
import unicodedata
from collections import OrderedDict
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any

import httpx
from pydantic import SecretStr

from app.world.types import (
    RawWorldEvent,
    SourceRef,
    WorldMode,
    WorldProviderHealth,
    WorldProviderName,
    WorldProviderState,
)

log = logging.getLogger("echo.world.worldmonitor")

PROVIDER = "world_monitor"
API_KEY_HEADER = "X-WorldMonitor-Key"
DEFAULT_BASE_URL = "https://api.worldmonitor.app"
DIGEST_PATH = "/api/news/v1/list-feed-digest"
DEFAULT_MCP_URL = "https://worldmonitor.app/mcp"
MCP_TOOL = "get_news_intelligence"
USER_AGENT = "ECHO/0.1 (+research)"
RETENTION_DAYS = 30
RPC_RATE_LIMITED = -32029
RPC_AUTH_CODES = (-32001, -32002)
REQUEST_TIMEOUT_S = 20.0
DEFAULT_RETRY_AFTER_S = 60.0
MAX_RETRY_AFTER_S = 86400.0  # daily-cap 429s count down to 00:00 UTC
MAX_BODY_BYTES = 10 * 1024 * 1024
HEADLINE_MAX = 500
BODY_MAX = 4000
DEFAULT_MAX_ITEMS = 300
DEFAULT_DEDUPE_SIZE = 5000
STALE_AFTER_INTERVALS = 3.0

Clock = Callable[[], datetime]
SleepFn = Callable[[float], Awaitable[None]]


# --------------------------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------------------------
class WorldProviderError(Exception):
    """Base class for adapter errors. Messages never contain the API key."""


class WorldProviderUnconfigured(WorldProviderError):
    """No API key configured: no request was (or will be) made."""


class WorldProviderAuthError(WorldProviderError):
    """HTTP 401/403: key missing/invalid or subscription inactive."""


class WorldRateLimited(WorldProviderError):
    """HTTP 429/503 (or a still-active Retry-After window). No request is made when raised early."""

    def __init__(self, retry_after_s: float, message: str | None = None) -> None:
        self.retry_after_s = float(retry_after_s)
        super().__init__(message or f"rate limited; retry after {self.retry_after_s:.0f}s")


class WorldProviderUnavailable(WorldProviderError, ConnectionError):
    """Network failure, 5xx, or an unusable response body."""


# --------------------------------------------------------------------------------------------
# Pure mapping helpers
# --------------------------------------------------------------------------------------------
_BIDI = {chr(c) for c in (0x202A, 0x202B, 0x202C, 0x202D, 0x202E, 0x2066, 0x2067, 0x2068, 0x2069)}
_WS = re.compile(r"\s+")
_KEY_LIKE = re.compile(r"wm_[A-Za-z0-9]{8,}")

_THREAT_SCORES: dict[str, float] = {
    "low": 0.25,
    "moderate": 0.5,
    "medium": 0.5,
    "elevated": 0.65,
    "high": 0.8,
    "critical": 1.0,
}


def sanitize_text(value: Any, max_len: int) -> str | None:
    """Strip control/bidi characters, collapse whitespace, cap length. None if empty/not text."""
    if not isinstance(value, str):
        return None
    cleaned = "".join(
        " " if ch in "\t\n\r" else ch
        for ch in value
        if ch in "\t\n\r" or (unicodedata.category(ch) != "Cc" and ch not in _BIDI)
    )
    cleaned = _WS.sub(" ", cleaned).strip()
    if not cleaned:
        return None
    return cleaned[:max_len].rstrip()


def _num(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        f = float(value)
        return f if math.isfinite(f) else None
    if isinstance(value, str):
        try:
            f = float(value.strip())
        except ValueError:
            return None
        return f if math.isfinite(f) else None
    return None


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def _parse_ts(value: Any) -> datetime | None:
    """Epoch seconds/ms (number or numeric string), ISO 8601 or RFC 2822 -> aware UTC."""
    if value is None or isinstance(value, bool):
        return None
    dt: datetime | None = None
    number = _num(value)
    try:
        if number is not None:
            if number <= 0:
                return None
            seconds = number / 1000.0 if number >= 1e11 else number
            dt = datetime.fromtimestamp(seconds, UTC)
        elif isinstance(value, str) and value.strip():
            text = value.strip()
            try:
                dt = datetime.fromisoformat(text)
            except ValueError:
                dt = parsedate_to_datetime(text)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            dt = dt.astimezone(UTC)
    except (OverflowError, OSError, ValueError, TypeError, IndexError):
        return None
    if dt is None or not (2000 <= dt.year <= 2100):
        return None
    return dt


def _threat_score(value: Any) -> float | None:
    if not isinstance(value, str):
        return None
    key = value.strip().lower().removeprefix("threat_level_")
    return _THREAT_SCORES.get(key)


def _safe_url(value: Any) -> str | None:
    text = sanitize_text(value, 2000)
    if text is None:
        return None
    if text.lower().startswith(("http://", "https://")) and " " not in text:
        return text
    return None


def _json_safe(value: Any, depth: int = 0) -> Any:
    """Bounded, JSON-serializable copy of a provider item (traceability without unbounded size)."""
    if depth > 4:
        return None
    if isinstance(value, str):
        return value[:1000]
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Mapping):
        return {str(k)[:100]: _json_safe(v, depth + 1) for k, v in list(value.items())[:50]}
    if isinstance(value, list | tuple):
        return [_json_safe(v, depth + 1) for v in list(value)[:50]]
    return None


def _first(item: Mapping[str, Any], *keys: str) -> Any:
    for k in keys:
        if item.get(k) is not None:
            return item[k]
    return None


def _str_list(value: Any, cap: int, max_len: int = 200) -> list[str]:
    if not isinstance(value, list | tuple):
        return []
    out: list[str] = []
    for v in value:
        s = sanitize_text(v, max_len)
        if s and s not in out:
            out.append(s)
        if len(out) >= cap:
            break
    return out


def map_worldmonitor_item(item: Any, retrieved_at: datetime) -> RawWorldEvent | None:
    """Map one World Monitor news item (digest ``NewsItem`` or MCP ``topStories`` entry) to a
    ``RawWorldEvent``. Unknown/malformed input returns None; never raises."""
    try:
        return _map_item(item, retrieved_at)
    except Exception:
        return None


def _map_item(item: Any, retrieved_at: datetime) -> RawWorldEvent | None:
    if not isinstance(item, Mapping):
        return None
    headline = sanitize_text(_first(item, "title", "primaryTitle", "headline"), HEADLINE_MAX)
    source_field = _first(item, "source", "primarySource")
    if source_field is None and isinstance(item.get("sources"), list) and item["sources"]:
        source_field = item["sources"][0]
    source_name = sanitize_text(source_field, 200)
    if headline is None or source_name is None:
        return None

    link = _safe_url(_first(item, "link", "primaryLink", "url"))
    published_at = _parse_ts(_first(item, "publishedAt", "pubDate", "published_at", "lastUpdated"))
    occurred_at = published_at or retrieved_at

    raw_id = item.get("id")
    if isinstance(raw_id, str | int) and not isinstance(raw_id, bool) and str(raw_id).strip():
        event_id = f"wm:{str(raw_id).strip()[:120]}"
    else:
        digest = hashlib.sha1((link or f"{source_name}|{headline}").encode("utf-8")).hexdigest()
        event_id = f"wm:{digest[:24]}"

    threat = item["threat"] if isinstance(item.get("threat"), Mapping) else {}
    threat_level = _first(item, "threatLevel") or threat.get("level")

    scores: dict[str, float] = {}
    importance = _num(_first(item, "effectiveImportanceScore", "importanceScore"))
    if importance is not None:
        scores["importance"] = _clamp01(importance / 100.0)
    credibility = _num(item.get("credibilityScore"))
    reliability: float | None = None
    if credibility is not None:
        reliability = _clamp01(credibility / 100.0)
        scores["credibility"] = reliability
    story_meta = item["storyMeta"] if isinstance(item.get("storyMeta"), Mapping) else {}
    unique_n: float | None = None
    for cand in (
        item.get("uniqueSourceCount"),
        item.get("corroborationCount"),
        story_meta.get("sourceCount"),
        item.get("sourceCount"),
    ):
        unique_n = _num(cand)
        if unique_n is not None:
            break
    if unique_n is not None and unique_n >= 0:
        scores["unique_sources"] = _clamp01(min(unique_n, 10.0) / 10.0)
    tscore = _threat_score(threat_level)
    if tscore is not None:
        scores["threat_level"] = tscore
    tconf = _num(threat.get("confidence"))
    if tconf is not None:
        scores["threat_confidence"] = _clamp01(tconf)

    categories: list[str] = []
    for c in (
        threat.get("category"),
        item.get("category") if isinstance(item.get("category"), str) else None,
        item.get("_category_bucket"),
    ):
        s = sanitize_text(c, 60)
        if s and s.lower() not in categories:
            categories.append(s.lower())

    country: str | None = None
    cc = item.get("countryCode")
    country_low_certainty = False
    if isinstance(cc, str) and re.fullmatch(r"[A-Za-z]{2}", cc.strip()):
        country = cc.strip().upper()
        country_low_certainty = True  # WM guesses countryCode from the headline
    elif isinstance(item.get("country"), str):
        country = sanitize_text(item["country"], 100)

    lat: float | None = None
    lon: float | None = None
    loc = item["location"] if isinstance(item.get("location"), Mapping) else item
    la, lo = _num(loc.get("latitude")), _num(loc.get("longitude"))
    if la is not None and lo is not None and -90 <= la <= 90 and -180 <= lo <= 180:
        lat, lon = la, lo

    entities: list[str] = []
    location_name = sanitize_text(item.get("locationName"), 200)
    if location_name:
        entities.append(location_name)

    body = sanitize_text(_first(item, "snippet", "summary", "description"), BODY_MAX)
    if body is not None and body == headline:  # identical to headline: no extra information
        body = None

    ref_meta: dict[str, Any] = {
        "retain_until": (retrieved_at + timedelta(days=RETENTION_DAYS)).isoformat()
    }
    contributing = _str_list(item.get("sources"), 12)
    if contributing:
        ref_meta["contributing_sources"] = contributing
    members = _str_list(item.get("memberTitles"), 10, HEADLINE_MAX)
    if members:
        ref_meta["member_titles"] = members
    if unique_n is not None:
        ref_meta["unique_source_count"] = unique_n
    tier = item.get("sourceTier")
    if isinstance(tier, int | float) and not isinstance(tier, bool):
        ref_meta["source_tier"] = tier
    if isinstance(item.get("sourceProvenance"), Mapping):
        ref_meta["source_provenance"] = _json_safe(item["sourceProvenance"])
    if isinstance(item.get("isAlert"), bool):
        ref_meta["is_alert"] = item["isAlert"]
    if isinstance(item.get("tickers"), list):
        ref_meta["tickers"] = _str_list(item["tickers"], 8, 12)
    if location_name:
        ref_meta["location_name"] = location_name
    if published_at is None:
        ref_meta["published_at_missing"] = True
    if country_low_certainty:
        ref_meta["country_certainty"] = "low"

    ref = SourceRef(
        provider=PROVIDER,
        source_name=source_name,
        source_url=link,
        source_identifier=event_id,
        headline=headline,
        published_at=published_at,
        retrieved_at=retrieved_at,
        reliability=reliability,
        metadata=ref_meta,
    )
    return RawWorldEvent(
        provider=PROVIDER,
        provider_event_id=event_id,
        headline=headline,
        body=body,
        occurred_at=occurred_at,
        sources=[ref],
        country=country,
        latitude=lat,
        longitude=lon,
        entities=entities,
        categories=categories,
        provider_scores=scores,
        is_replay=False,
    )


def extract_worldmonitor_items(payload: Any, _depth: int = 0) -> list[Any] | None:
    """Locate item dicts in a digest / MCP ``get_news_intelligence`` payload.

    Returns None when the payload has no recognized item container (unusable response); an empty
    list for a valid-but-empty response. Digest items are tagged with ``_category_bucket``.
    """
    if _depth > 4:
        return None
    if isinstance(payload, list):
        return list(payload)
    if not isinstance(payload, Mapping):
        return None
    found = False
    out: list[Any] = []
    cats = payload.get("categories")
    if isinstance(cats, Mapping):
        found = True
        for name, bucket in cats.items():
            items = bucket.get("items") if isinstance(bucket, Mapping) else None
            if isinstance(items, list):
                for it in items:
                    out.append(
                        {**it, "_category_bucket": str(name)} if isinstance(it, dict) else it
                    )
    for key in ("topStories", "items"):
        if isinstance(payload.get(key), list):
            found = True
            out.extend(payload[key])
    for key in ("insights", "data", "structuredContent", "result"):
        nested = payload.get(key)
        if isinstance(nested, Mapping):
            sub = extract_worldmonitor_items(nested, _depth + 1)
            if sub is not None:
                found = True
                out.extend(sub)
    return out if found else None


_UNDECODABLE = object()


def decode_body(resp: httpx.Response) -> Any:
    """JSON body, or last ``data:`` event of an SSE (Streamable HTTP) reply; sentinel if neither."""
    text = resp.text
    ctype = resp.headers.get("content-type", "")
    if "text/event-stream" in ctype or text.lstrip().startswith(("event:", "data:")):
        data = [ln[5:].strip() for ln in text.splitlines() if ln.startswith("data:")]
        text = data[-1] if data else ""
    try:
        return json.loads(text)
    except ValueError:
        return _UNDECODABLE


def unwrap_mcp_result(payload: Any) -> Any:
    """MCP ``tools/call`` reply -> tool payload (``structuredContent`` or the JSON text block)."""
    if not (isinstance(payload, Mapping) and isinstance(payload.get("result"), Mapping)):
        return payload
    result = payload["result"]
    if isinstance(result.get("structuredContent"), Mapping):
        return result["structuredContent"]
    content = result.get("content")
    if isinstance(content, list):
        for block in content:
            if isinstance(block, Mapping) and isinstance(block.get("text"), str):
                try:
                    return json.loads(block["text"])
                except ValueError:
                    continue
    return result


def parse_retry_after(value: str | None, now: datetime, default: float) -> float:
    """Retry-After as delta-seconds or HTTP-date -> seconds in [1, MAX_RETRY_AFTER_S]."""
    if value is None or not value.strip():
        return default
    text = value.strip()
    secs = _num(text)
    if secs is None:
        try:
            when = parsedate_to_datetime(text)
            if when.tzinfo is None:
                when = when.replace(tzinfo=UTC)
            secs = (when - now).total_seconds()
        except (ValueError, TypeError, IndexError):
            return default
    return max(1.0, min(float(secs), MAX_RETRY_AFTER_S))


# --------------------------------------------------------------------------------------------
# Provider
# --------------------------------------------------------------------------------------------
def _utcnow() -> datetime:
    return datetime.now(UTC)


class WorldMonitorProvider:
    name: WorldProviderName = WorldProviderName.WORLD_MONITOR

    def __init__(
        self,
        api_key: str | SecretStr | None,
        base_url: str = DEFAULT_BASE_URL,
        poll_interval_s: float = 1800.0,
        client_factory: Callable[[], httpx.AsyncClient] | None = None,
        clock: Clock = _utcnow,
        sleep: SleepFn | None = None,
        variant: str = "full",
        mode: str = "rest",
        mcp_url: str = DEFAULT_MCP_URL,
        max_items: int = DEFAULT_MAX_ITEMS,
        dedupe_size: int = DEFAULT_DEDUPE_SIZE,
    ) -> None:
        if poll_interval_s <= 0:
            raise ValueError("poll_interval_s must be > 0")
        if isinstance(api_key, SecretStr):
            api_key = api_key.get_secret_value()
        key = api_key.strip() if isinstance(api_key, str) else None
        self._api_key: str | None = key or None
        self._base_url = base_url.rstrip("/")
        self._poll_interval_s = float(poll_interval_s)
        self._client_factory = client_factory or (
            lambda: httpx.AsyncClient(timeout=REQUEST_TIMEOUT_S)
        )
        self._clock = clock
        self._sleep = sleep
        self._variant = variant
        if mode not in ("rest", "mcp"):
            raise ValueError("mode must be 'rest' or 'mcp'")
        self._mode = mode
        self._mcp_url = mcp_url
        self._max_items = max(1, max_items)
        self._dedupe_size = max(1, dedupe_size)

        self._client: httpx.AsyncClient | None = None
        self._lock = asyncio.Lock()
        self._stop = asyncio.Event()
        self._seen: OrderedDict[str, None] = OrderedDict()

        self._state = (
            WorldProviderState.CONNECTING if self._api_key else WorldProviderState.UNCONFIGURED
        )
        self._last_success_at: datetime | None = None
        self._last_event_at: datetime | None = None
        self._received = 0
        self._malformed = 0
        self._last_error: str | None = None
        self._retry_after_until: datetime | None = None
        self._next_allowed_at: datetime | None = None
        self._last_outcome: str | None = None  # ok | rate | error
        self._cache: list[RawWorldEvent] = []

    def __repr__(self) -> str:
        return (
            f"WorldMonitorProvider(configured={self.configured}, base_url={self._base_url!r}, "
            f"poll_interval_s={self._poll_interval_s})"
        )

    # ---- public properties -------------------------------------------------------------
    @property
    def configured(self) -> bool:
        return self._api_key is not None

    @property
    def min_interval_s(self) -> float:
        """Minimum seconds between upstream requests (WM quota is small)."""
        return self._poll_interval_s

    # ---- redaction ---------------------------------------------------------------------
    def _redact(self, text: str) -> str:
        if self._api_key:
            text = text.replace(self._api_key, "[REDACTED]")
        return _KEY_LIKE.sub("[REDACTED]", text)[:300]

    def _fail(self, state: WorldProviderState, message: str) -> str:
        msg = self._redact(message)
        self._state = state
        self._last_error = msg
        return msg

    # ---- lifecycle ---------------------------------------------------------------------
    async def connect(self) -> None:
        if not self._api_key:
            raise WorldProviderUnconfigured("World Monitor API key not configured")
        self._stop.clear()
        if self._client is None:
            self._client = self._client_factory()
        if self._last_success_at is None:
            self._state = WorldProviderState.CONNECTING

    async def disconnect(self) -> None:
        self._stop.set()
        client, self._client = self._client, None
        if client is not None:
            with contextlib.suppress(Exception):
                await client.aclose()

    # ---- health ------------------------------------------------------------------------
    def health(self) -> WorldProviderHealth:
        state = self._state
        if (
            state == WorldProviderState.HEALTHY
            and self._last_success_at is not None
            and (self._clock() - self._last_success_at).total_seconds()
            > STALE_AFTER_INTERVALS * self._poll_interval_s
        ):
            state = WorldProviderState.STALE
        mode = WorldMode.LIVE if state == WorldProviderState.HEALTHY else WorldMode.OFFLINE
        return WorldProviderHealth(
            provider=self.name,
            configured=self.configured,
            state=state,
            mode=mode,
            last_success_at=self._last_success_at,
            last_event_at=self._last_event_at,
            events_received=self._received,
            malformed_events=self._malformed,
            last_error=self._last_error,
            poll_interval_s=self._poll_interval_s,
            retry_after_until=self._retry_after_until,
        )

    # ---- polling -----------------------------------------------------------------------
    async def fetch_recent(self, since: datetime | None = None) -> list[RawWorldEvent]:
        """One poll (at most one request). Within ``min_interval_s`` of the last attempt, or during
        an active Retry-After window, no request is made: the cached result (or the recorded rate
        limit) is returned instead."""
        if not self._api_key:
            raise WorldProviderUnconfigured("World Monitor API key not configured")
        async with self._lock:
            now = self._clock()
            if self._retry_after_until is not None and now < self._retry_after_until:
                raise WorldRateLimited((self._retry_after_until - now).total_seconds())
            if self._next_allowed_at is not None and now < self._next_allowed_at:
                if self._last_outcome == "ok":
                    return self._filter(self._cache, since)
                return []
            return self._filter(await self._request(now), since)

    @staticmethod
    def _filter(events: list[RawWorldEvent], since: datetime | None) -> list[RawWorldEvent]:
        return [e for e in events if since is None or e.occurred_at > since]

    async def _send(self, now: datetime) -> httpx.Response:
        assert self._api_key is not None and self._client is not None
        headers = {
            API_KEY_HEADER: self._api_key,
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        }
        if self._mode == "mcp":
            headers["Accept"] = "application/json, text/event-stream"
            body = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": MCP_TOOL, "arguments": {"limit": self._max_items}},
            }
            return await self._client.post(
                self._mcp_url, json=body, headers=headers, timeout=REQUEST_TIMEOUT_S
            )
        return await self._client.get(
            f"{self._base_url}{DIGEST_PATH}",
            params={"variant": self._variant},
            headers=headers,
            timeout=REQUEST_TIMEOUT_S,
        )

    def _rate_limited(self, now: datetime, retry: float, label: str) -> WorldRateLimited:
        self._retry_after_until = now + timedelta(seconds=retry)
        if self._next_allowed_at is None or self._next_allowed_at < self._retry_after_until:
            self._next_allowed_at = self._retry_after_until
        self._last_outcome = "rate"
        msg = self._fail(WorldProviderState.DEGRADED, f"{label}; retry after {retry:.0f}s")
        log.warning("world_monitor_rate_limited", extra={"label": label, "retry_after_s": retry})
        return WorldRateLimited(retry, msg)

    def _auth_error(self, label: str, reason: str) -> WorldProviderAuthError:
        self._last_outcome = "error"
        msg = self._fail(WorldProviderState.ERROR, f"{label}: {reason}")
        log.error("world_monitor_auth_error", extra={"label": label})
        return WorldProviderAuthError(msg)

    async def _request(self, now: datetime) -> list[RawWorldEvent]:
        assert self._api_key is not None
        if self._client is None:
            self._client = self._client_factory()
        self._next_allowed_at = now + timedelta(seconds=self._poll_interval_s)
        try:
            resp = await self._send(now)
        except httpx.HTTPError as exc:
            self._last_outcome = "error"
            msg = self._fail(
                WorldProviderState.DEGRADED, f"network error: {type(exc).__name__}: {exc}"
            )
            log.warning("world_monitor_network_error", extra={"error": msg})
            raise WorldProviderUnavailable(msg) from None

        status = resp.status_code
        if status in (429, 503):
            retry = parse_retry_after(resp.headers.get("Retry-After"), now, DEFAULT_RETRY_AFTER_S)
            raise self._rate_limited(now, retry, f"HTTP {status}")
        if status in (401, 403):
            reason = "invalid or missing API key" if status == 401 else "subscription inactive"
            raise self._auth_error(f"HTTP {status}", reason)
        if status < 200 or status >= 300:
            self._last_outcome = "error"
            state = WorldProviderState.DEGRADED if status >= 500 else WorldProviderState.ERROR
            raise WorldProviderUnavailable(self._fail(state, f"HTTP {status}"))

        events = self._parse(resp, now)
        self._last_outcome = "ok"
        self._state = WorldProviderState.HEALTHY
        self._last_error = None
        self._retry_after_until = None
        self._last_success_at = now
        self._cache = events
        self._received += len(events)
        if events:
            self._last_event_at = max(e.occurred_at for e in events)
        return events

    def _parse_failure(self, message: str, *, malformed: bool) -> WorldProviderUnavailable:
        self._last_outcome = "error"
        if malformed:
            self._malformed += 1
        return WorldProviderUnavailable(self._fail(WorldProviderState.DEGRADED, message))

    def _parse(self, resp: httpx.Response, now: datetime) -> list[RawWorldEvent]:
        if len(resp.content) > MAX_BODY_BYTES:
            raise self._parse_failure("response too large", malformed=False)
        payload = decode_body(resp)
        if payload is _UNDECODABLE:
            raise self._parse_failure("response is not valid JSON", malformed=True)
        if isinstance(payload, Mapping) and isinstance(payload.get("error"), Mapping):
            # JSON-RPC error delivered with HTTP 200 (per-minute limiter = -32029)
            code = payload["error"].get("code")
            if code == RPC_RATE_LIMITED:
                retry = parse_retry_after(
                    resp.headers.get("Retry-After"), now, DEFAULT_RETRY_AFTER_S
                )
                raise self._rate_limited(now, retry, "JSON-RPC -32029")
            if code in RPC_AUTH_CODES:
                raise self._auth_error(
                    f"JSON-RPC {code}", "authentication or subscription required"
                )
            raise self._parse_failure(f"JSON-RPC error {code}", malformed=False)
        payload = unwrap_mcp_result(payload)
        items = extract_worldmonitor_items(payload)
        if items is None:
            raise self._parse_failure("unrecognized response shape", malformed=True)
        by_id: dict[str, RawWorldEvent] = {}
        for item in items:
            ev = map_worldmonitor_item(item, now)
            if ev is None:
                self._malformed += 1
                continue
            eid = ev.provider_event_id or ""
            prev = by_id.get(eid)
            if prev is None:
                by_id[eid] = ev
            else:  # same story seen in several digest categories: merge tags
                merged = list(dict.fromkeys([*prev.categories, *ev.categories]))
                by_id[eid] = prev.model_copy(update={"categories": merged})
        events = list(by_id.values())
        if len(events) > self._max_items:
            events.sort(key=lambda e: -e.provider_scores.get("importance", 0.0))
            events = events[: self._max_items]
        events.sort(key=lambda e: (e.occurred_at, e.provider_event_id or ""))
        return events

    # ---- streaming ---------------------------------------------------------------------
    def _remember(self, event_id: str) -> bool:
        """True if new. Bounded LRU of seen ids."""
        if event_id in self._seen:
            self._seen.move_to_end(event_id)
            return False
        self._seen[event_id] = None
        while len(self._seen) > self._dedupe_size:
            self._seen.popitem(last=False)
        return True

    async def _wait(self, seconds: float) -> None:
        if self._sleep is not None:
            await self._sleep(seconds)
            return
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._stop.wait(), timeout=seconds)

    def _next_delay(self) -> float:
        delay = self._poll_interval_s
        now = self._clock()
        if self._retry_after_until is not None and self._retry_after_until > now:
            delay = max(delay, (self._retry_after_until - now).total_seconds())
        return delay

    async def stream(self) -> AsyncIterator[RawWorldEvent]:
        """Poll loop: fetch -> yield unseen events -> wait. Provider errors are absorbed into
        ``health()``. Ends when unconfigured or after ``disconnect()``."""
        if not self._api_key:
            return
        if self._client is None:
            await self.connect()
        while not self._stop.is_set():
            try:
                events = await self.fetch_recent()
            except WorldProviderUnconfigured:
                return
            except WorldProviderError:
                events = []  # already recorded in health()
            except Exception as exc:
                self._fail(WorldProviderState.DEGRADED, f"unexpected error: {type(exc).__name__}")
                events = []
            for ev in events:
                if self._stop.is_set():
                    return
                if ev.provider_event_id is None or self._remember(ev.provider_event_id):
                    yield ev
            if self._stop.is_set():
                return
            await self._wait(self._next_delay())
