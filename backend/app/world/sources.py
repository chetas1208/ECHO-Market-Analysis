"""Publisher-family grouping and source-independence classification (Day 3, deterministic).

``source_group`` maps a (name, url) pair to a publisher family (``reuters``, ``ap``, ...). It is
matched by URL registrable domain first (no network, no DNS, no public-suffix list; a small
built-in multi-part-TLD set), then by normalized publisher name, then falls back to the
registrable domain or a name slug. A known aggregator domain (Yahoo Finance, MSN, ...) defers to
a known wire/publisher *name* when one is given (e.g. name "Reuters" served from yahoo.com is the
``reuters`` family).

``classify_independence`` decides, per ``SourceRef``, whether it is independent evidence:

* The *claimed group* of a ref is its attributed origin when one is found, else its own group.
  Origin is taken (in order) from ``SourceRef.syndicated_from``, attribution markers in
  ``headline`` and in ``metadata['byline'|'credit'|'attribution']`` ("(Reuters)", "via Reuters",
  "Reuters contributed", "reporting by Reuters", "courtesy of Reuters"). An origin equal to the
  ref's own group is ignored (a Reuters item saying "(Reuters)" is simply Reuters).
* Exactly one ref per claimed group is independent; all others are duplicate/syndicated copies
  (``independent=False``, ``syndicated_of=<claimed group>``). The representative is the ref whose
  own group *is* the claimed group (the original) if present, else the first credit-copy, so the
  result does not depend on whether the original is listed before or after its republications.
* Aggregators (Yahoo Finance, MSN, Google News, Investing.com, World Monitor) with an attributed
  origin are never independent; without a determinable origin they count as their own group.
* A non-aggregator republication whose origin is not in the list represents that origin once
  (independent, but ``syndicated_of`` still names the origin for transparency).

Limitations (by design; no network, no text model):
* Paraphrased or rewritten copies with no attribution marker are undetectable and count as
  independent; near-identical text without a credit is likewise not compared.
* Attribution is only recognized for the built-in publisher families; a credit to an unknown
  outlet is honoured only via ``syndicated_from`` (and matches only if its slug/domain equals the
  other ref's group).
* Ownership links (e.g. two outlets of one media group) are not modelled; only listed families.
* Generic hosting domains (medium.com, substack.com, social platforms) group by domain, not author.
* Refs with neither name nor usable URL share the group ``unknown`` and count as one source.
* Citations ("according to Reuters") are not treated as syndication; only credit markers are.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from ipaddress import ip_address
from typing import Any
from urllib.parse import urlsplit

from app.world.types import SourceRef

UNKNOWN_GROUP = "unknown"

# group -> normalized name aliases (see _normalize_name).
_WIRE_ALIASES: dict[str, tuple[str, ...]] = {
    "reuters": (
        "reuters",
        "thomson reuters",
        "reuters news",
        "reuters news agency",
        "reuters agency",
    ),
    "ap": ("ap", "ap news", "associated press", "the associated press"),
    "afp": ("afp", "agence france presse", "agence france-presse"),
    "bloomberg": ("bloomberg", "bloomberg news", "bloomberg l p"),
    "dow_jones": (
        "dow jones",
        "dow jones newswires",
        "wsj",
        "wall street journal",
        "the wall street journal",
    ),
    "ft": ("ft", "financial times", "the financial times"),
    "bbc": ("bbc", "bbc news", "british broadcasting corporation"),
    "cnbc": ("cnbc",),
    "al_jazeera": ("al jazeera", "aljazeera", "al jazeera english"),
    "xinhua": ("xinhua", "xinhua news", "xinhua news agency"),
    "tass": ("tass", "tass news agency"),
    "nhk": ("nhk", "nhk world", "nhk world japan"),
    "nikkei": ("nikkei", "nikkei asia", "nikkei asian review"),
    "kyodo": ("kyodo", "kyodo news"),
    "upi": ("upi", "united press international"),
}
_AGGREGATOR_ALIASES: dict[str, tuple[str, ...]] = {
    "yahoo_finance": ("yahoo finance", "yahoo news", "yahoo"),
    "msn": ("msn", "msn news", "microsoft start"),
    "google_news": ("google news",),
    "investing_com": ("investing", "investing com"),
    "world_monitor": ("world monitor", "worldmonitor"),
}
AGGREGATOR_GROUPS: frozenset[str] = frozenset(_AGGREGATOR_ALIASES)

# host (registrable domain or specific host) -> group. Suffix-walked, so subdomains match.
_DOMAIN_GROUPS: dict[str, str] = {
    "reuters.com": "reuters",
    "reutersagency.com": "reuters",
    "thomsonreuters.com": "reuters",
    "apnews.com": "ap",
    "ap.org": "ap",
    "afp.com": "afp",
    "bloomberg.com": "bloomberg",
    "wsj.com": "dow_jones",
    "dowjones.com": "dow_jones",
    "ft.com": "ft",
    "bbc.com": "bbc",
    "bbc.co.uk": "bbc",
    "cnbc.com": "cnbc",
    "aljazeera.com": "al_jazeera",
    "aljazeera.net": "al_jazeera",
    "xinhuanet.com": "xinhua",
    "news.cn": "xinhua",
    "tass.com": "tass",
    "tass.ru": "tass",
    "nhk.or.jp": "nhk",
    "nikkei.com": "nikkei",
    "kyodonews.net": "kyodo",
    "upi.com": "upi",
    "yahoo.com": "yahoo_finance",
    "msn.com": "msn",
    "news.google.com": "google_news",
    "investing.com": "investing_com",
    "worldmonitor.app": "world_monitor",
}

# Public-suffix second levels we treat as two-label suffixes (registrable = 3 labels).
_TWO_LABEL_SUFFIXES = frozenset(
    {
        "co.uk", "org.uk", "ac.uk", "gov.uk", "com.au", "net.au", "org.au", "co.jp", "or.jp",
        "ne.jp", "co.nz", "co.in", "com.cn", "com.hk", "com.sg", "com.br", "com.tw", "co.kr",
        "co.za", "com.tr", "com.mx", "com.ar",
    }
)  # fmt: skip
_CORP_SUFFIXES = frozenset(
    {"inc", "ltd", "llc", "corp", "corporation", "group", "plc", "co", "limited", "com", "online"}
)

_NAME_TO_GROUP: dict[str, str] = {}


def _normalize_name(name: str | None) -> str:
    """Lowercase, accent-stripped, punctuation-free, corporate-suffix-free publisher name."""
    if not name:
        return ""
    text = unicodedata.normalize("NFKD", str(name))
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    text = text.replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text).strip()
    words = text.split()
    if words and words[0] == "the" and len(words) > 1:
        words = words[1:]
    while len(words) > 1 and words[-1] in _CORP_SUFFIXES:
        words.pop()
    return " ".join(words)


def _build_name_table() -> None:
    for table in (_WIRE_ALIASES, _AGGREGATOR_ALIASES):
        for group, aliases in table.items():
            _NAME_TO_GROUP[_normalize_name(group)] = group
            for alias in aliases:
                _NAME_TO_GROUP[_normalize_name(alias)] = group


_build_name_table()
# Prefix matching ("Reuters Business", "Bloomberg Markets") only for long, non-aggregator aliases.
_PREFIX_ALIASES: tuple[tuple[str, str], ...] = tuple(
    sorted(
        (
            (alias, group)
            for alias, group in _NAME_TO_GROUP.items()
            if len(alias) >= 6 and group not in AGGREGATOR_GROUPS
        ),
        key=lambda item: (-len(item[0]), item[0]),
    )
)


def _group_from_name(name: str | None) -> str | None:
    key = _normalize_name(name)
    if not key:
        return None
    hit = _NAME_TO_GROUP.get(key)
    if hit:
        return hit
    for alias, group in _PREFIX_ALIASES:
        if key.startswith(alias + " "):
            return group
    return None


def _host(url: str | None) -> str | None:
    """Lowercased hostname from a URL or bare domain; None when unusable."""
    if not url or not isinstance(url, str):
        return None
    raw = url.strip()
    if not raw or re.search(r"\s", raw):
        return None
    try:
        parts = urlsplit(raw if "//" in raw else "//" + raw)
        host = parts.hostname
    except ValueError:
        return None
    if not host:
        return None
    host = host.strip(".").lower()
    return host or None


def _registrable(host: str) -> str:
    try:
        ip_address(host)
        return host
    except ValueError:
        pass
    labels = host.split(".")
    if len(labels) <= 2:
        return host
    if ".".join(labels[-2:]) in _TWO_LABEL_SUFFIXES:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def _group_from_host(host: str) -> str | None:
    labels = host.split(".")
    for i in range(len(labels) - 1):
        hit = _DOMAIN_GROUPS.get(".".join(labels[i:]))
        if hit:
            return hit
    return None


def _slug(name: str | None) -> str:
    key = _normalize_name(name)
    return key.replace(" ", "_") if key else ""


def source_group(source_name: str, source_url: str | None = None) -> str:
    """Publisher family for a source: known family, else registrable domain, else name slug."""
    host = _host(source_url)
    domain_group = _group_from_host(host) if host else None
    if domain_group and domain_group not in AGGREGATOR_GROUPS:
        return domain_group
    name_group = _group_from_name(source_name)
    if domain_group:  # aggregator domain: a known wire/publisher name wins
        return name_group if name_group and name_group not in AGGREGATOR_GROUPS else domain_group
    if name_group:
        return name_group
    if host:
        return _registrable(host)
    return _slug(source_name) or UNKNOWN_GROUP


def _canonical_group(value: str | None) -> str | None:
    """Canonical group for a free-form group/publisher label (syndicated_from, source_group)."""
    if not value or not isinstance(value, str) or not value.strip():
        return None
    named = _group_from_name(value)
    if named:
        return named
    text = value.strip()
    if "." in text and not re.search(r"\s", text):
        host = _host(text)
        if host:
            return _group_from_host(host) or _registrable(host)
    return _slug(text) or None


# --- attribution markers -------------------------------------------------------------------


def _alias_pattern(alias: str) -> str:
    return r"[\s\-]+".join(re.escape(tok) for tok in alias.split())


_ATTR_ALIASES = sorted(
    (a for a, g in _NAME_TO_GROUP.items() if g not in AGGREGATOR_GROUPS),
    key=lambda a: (-len(a), a),
)
_A = "(?:" + "|".join(_alias_pattern(a) for a in _ATTR_ALIASES) + ")"
_MARKERS = tuple(
    re.compile(p)
    for p in (
        rf"\(\s*({_A})(?:\s*(?:[/,&]|and)\s*{_A})*\s*\)",
        rf"\bvia\s+({_A})\b",
        rf"\b({_A})\s+contributed\b",
        rf"\breporting\s+by\s+({_A})\b",
        rf"\bcourtesy\s+of\s+({_A})\b",
    )
)
_BYLINE_ANY = re.compile(rf"\b({_A})\b")
_BYLINE_KEYS = ("byline", "credit", "attribution")


def _find_origin(text: str, *, loose: bool) -> str | None:
    """Earliest attribution marker in ``text`` -> group; ``loose`` also accepts a bare name."""
    lowered = re.sub(r"\s+", " ", unicodedata.normalize("NFKD", text).lower())
    best: tuple[int, str] | None = None
    for pattern in (*_MARKERS, *((_BYLINE_ANY,) if loose else ())):
        m = pattern.search(lowered)
        if m and (best is None or m.start(1) < best[0]):
            best = (m.start(1), m.group(1))
    if best is None:
        return None
    return _group_from_name(best[1])


def _attributed_origin(ref: SourceRef) -> str | None:
    if ref.syndicated_from:
        origin = _canonical_group(ref.syndicated_from)
        if origin:
            return origin
    if ref.headline:
        origin = _find_origin(ref.headline, loose=False)
        if origin:
            return origin
    meta = ref.metadata if isinstance(ref.metadata, dict) else {}
    for key in _BYLINE_KEYS:
        value: Any = meta.get(key)
        if isinstance(value, str) and value.strip():
            origin = _find_origin(value, loose=True)
            if origin:
                return origin
    return None


# --- independence ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SourceIndependence:
    ref_index: int
    group: str  # the ref's own publisher family
    independent: bool
    syndicated_of: str | None = None  # origin/claimed group when a copy or credited republication


def classify_independence(refs: Sequence[SourceRef]) -> list[SourceIndependence]:
    """One ``SourceIndependence`` per ref, in input order. See module docstring for the rules."""
    own: list[str] = []
    origin: list[str | None] = []
    for ref in refs:
        group = _canonical_group(ref.source_group) or source_group(ref.source_name, ref.source_url)
        org = _attributed_origin(ref)
        own.append(group)
        origin.append(org if org and org != group else None)

    claimed = [origin[i] or own[i] for i in range(len(refs))]
    blocked = [own[i] in AGGREGATOR_GROUPS and origin[i] is not None for i in range(len(refs))]

    representative: dict[str, int] = {}
    for i, group in enumerate(claimed):  # the original itself wins, else the first credit copy
        if not blocked[i] and own[i] == group and group not in representative:
            representative[group] = i
    for i, group in enumerate(claimed):
        if not blocked[i] and group not in representative:
            representative[group] = i

    out: list[SourceIndependence] = []
    for i in range(len(refs)):
        independent = representative.get(claimed[i]) == i
        syndicated_of = origin[i] if independent else claimed[i]
        out.append(SourceIndependence(i, own[i], independent, syndicated_of))
    return out
