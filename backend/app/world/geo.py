"""Deterministic geography normalization for world events (no ML, no network, no guessing).

``normalize_geo(raw, entities)`` builds a :class:`GeoInfo` from, in this order of trust:

1. Upstream fields on the raw event (``country``, ``region``, ``city``, ``latitude``/
   ``longitude``). Upstream coordinates are preserved EXACTLY (same float, never rounded or
   overwritten). A lone latitude or longitude is unusable and treated as absent.
2. Normalized entities (duck-typed: objects with ``.canonical`` and ``.kind``): the first
   ``country`` entity when the raw country is missing/unrecognized, first ``city`` entity when
   ``raw.city`` is missing, first ``region`` entity as a region fallback.
3. The chokepoint gazetteer: a chokepoint fills latitude/longitude/region ONLY when it is
   actually named (in entities, ``raw.entities`` or headline/body, word-boundary matched).
   It never overrides upstream coordinates or an already-known region.

Countries are never extracted from free text here (that is ``entities.py``' job); ambiguous
names are not guessed. If nothing resolves, the result is ``GeoInfo(resolved=False)`` with all
fields ``None``. Known limitation: with several country entities the first (provider-supplied
first, then text order) wins; a chokepoint named alongside an unrelated country keeps both
(country stays, chokepoint wins ``location_key``).

``location_key(geo)`` priority: chokepoint > city > country > region > ``"unknown"``; keys are
lowercase slugs with a kind prefix, e.g. ``chokepoint:strait-of-hormuz``, ``city:us:new-york``,
``country:ir``, ``region:middle-east``.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from app.world.types import GeoInfo, RawWorldEvent


class EntityLike(Protocol):
    canonical: str
    kind: str


# --------------------------------------------------------------------------- normalization


def _norm(text: str) -> str:
    """Lowercase, strip accents, drop '.' and apostrophes, other punctuation -> single space."""
    s = unicodedata.normalize("NFKD", text)
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    s = s.replace(".", "").replace("'", "").replace("\u2019", "")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return s.strip()


def _slug(text: str) -> str:
    return _norm(text).replace(" ", "-")


# --------------------------------------------------------------------------- regions

_REGIONS: tuple[str, ...] = (
    "North America",
    "Latin America",
    "Europe",
    "Middle East",
    "Africa",
    "East Asia",
    "South Asia",
    "Southeast Asia",
    "Central Asia",
    "Oceania",
)
_REGION_ALIASES: dict[str, str] = {_norm(r): r for r in _REGIONS} | {
    "mideast": "Middle East",
    "middle eastern": "Middle East",
    "south east asia": "Southeast Asia",
}

# --------------------------------------------------------------------------- countries

# (ISO2, display name, region, aliases...)
_COUNTRIES: tuple[tuple[str, ...], ...] = (
    (
        "US",
        "United States",
        "North America",
        "US",
        "U.S.",
        "USA",
        "U.S.A.",
        "United States of America",
    ),
    ("CA", "Canada", "North America"),
    ("MX", "Mexico", "Latin America"),
    ("BR", "Brazil", "Latin America", "Brasil"),
    ("AR", "Argentina", "Latin America"),
    ("CL", "Chile", "Latin America"),
    ("CO", "Colombia", "Latin America"),
    ("PE", "Peru", "Latin America"),
    ("VE", "Venezuela", "Latin America"),
    ("CU", "Cuba", "Latin America"),
    ("PA", "Panama", "Latin America"),
    ("EC", "Ecuador", "Latin America"),
    ("GB", "United Kingdom", "Europe", "UK", "U.K.", "Britain", "Great Britain"),
    ("FR", "France", "Europe"),
    ("DE", "Germany", "Europe", "Deutschland"),
    ("IT", "Italy", "Europe"),
    ("ES", "Spain", "Europe"),
    ("PT", "Portugal", "Europe"),
    ("NL", "Netherlands", "Europe", "The Netherlands", "Holland"),
    ("BE", "Belgium", "Europe"),
    ("CH", "Switzerland", "Europe"),
    ("SE", "Sweden", "Europe"),
    ("NO", "Norway", "Europe"),
    ("DK", "Denmark", "Europe"),
    ("FI", "Finland", "Europe"),
    ("IE", "Ireland", "Europe"),
    ("AT", "Austria", "Europe"),
    ("PL", "Poland", "Europe"),
    ("CZ", "Czechia", "Europe", "Czech Republic"),
    ("HU", "Hungary", "Europe"),
    ("RO", "Romania", "Europe"),
    ("GR", "Greece", "Europe"),
    ("UA", "Ukraine", "Europe"),
    ("BY", "Belarus", "Europe"),
    ("RU", "Russia", "Europe", "Russian Federation"),
    ("TR", "Turkey", "Middle East", "Turkiye", "Republic of Turkey"),
    ("IR", "Iran", "Middle East", "Islamic Republic of Iran"),
    ("IQ", "Iraq", "Middle East"),
    ("SA", "Saudi Arabia", "Middle East", "KSA", "Kingdom of Saudi Arabia"),
    ("AE", "United Arab Emirates", "Middle East", "UAE", "U.A.E."),
    ("IL", "Israel", "Middle East"),
    (
        "PS",
        "Palestine",
        "Middle East",
        "State of Palestine",
        "Palestinian Territories",
        "West Bank",
        "Gaza",
        "Gaza Strip",
    ),
    ("QA", "Qatar", "Middle East"),
    ("KW", "Kuwait", "Middle East"),
    ("OM", "Oman", "Middle East"),
    ("YE", "Yemen", "Middle East"),
    ("SY", "Syria", "Middle East"),
    ("LB", "Lebanon", "Middle East"),
    ("JO", "Jordan", "Middle East"),
    ("BH", "Bahrain", "Middle East"),
    ("EG", "Egypt", "Africa"),
    ("ZA", "South Africa", "Africa"),
    ("NG", "Nigeria", "Africa"),
    ("KE", "Kenya", "Africa"),
    ("ET", "Ethiopia", "Africa"),
    ("DZ", "Algeria", "Africa"),
    ("MA", "Morocco", "Africa"),
    ("LY", "Libya", "Africa"),
    ("SD", "Sudan", "Africa"),
    ("GH", "Ghana", "Africa"),
    ("CN", "China", "East Asia", "PRC", "People's Republic of China", "Mainland China"),
    ("JP", "Japan", "East Asia"),
    ("KR", "South Korea", "East Asia", "Republic of Korea", "Korea, South"),
    ("KP", "North Korea", "East Asia", "DPRK", "Korea, North"),
    ("TW", "Taiwan", "East Asia", "Chinese Taipei"),
    ("IN", "India", "South Asia"),
    ("PK", "Pakistan", "South Asia"),
    ("BD", "Bangladesh", "South Asia"),
    ("LK", "Sri Lanka", "South Asia"),
    ("AF", "Afghanistan", "South Asia"),
    ("ID", "Indonesia", "Southeast Asia"),
    ("MY", "Malaysia", "Southeast Asia"),
    ("SG", "Singapore", "Southeast Asia"),
    ("TH", "Thailand", "Southeast Asia"),
    ("VN", "Vietnam", "Southeast Asia", "Viet Nam"),
    ("PH", "Philippines", "Southeast Asia", "The Philippines"),
    ("MM", "Myanmar", "Southeast Asia", "Burma"),
    ("KZ", "Kazakhstan", "Central Asia"),
    ("UZ", "Uzbekistan", "Central Asia"),
    ("AU", "Australia", "Oceania"),
    ("NZ", "New Zealand", "Oceania"),
)


@dataclass(frozen=True)
class _Country:
    iso2: str
    name: str
    region: str


_COUNTRY_BY_KEY: dict[str, _Country] = {}
_COUNTRY_BY_ISO2: dict[str, _Country] = {}
for _row in _COUNTRIES:
    _c = _Country(_row[0], _row[1], _row[2])
    _COUNTRY_BY_ISO2[_c.iso2] = _c
    for _name in (_row[1], *_row[3:]):
        _COUNTRY_BY_KEY.setdefault(_norm(_name), _c)
    # a bare 2-letter ISO code is only honoured for the raw ``country`` field (see below)


def _lookup_country(value: str | None, *, allow_iso2: bool) -> _Country | None:
    if not value or not value.strip():
        return None
    v = value.strip()
    if allow_iso2 and len(v) == 2 and v.isalpha():
        hit = _COUNTRY_BY_ISO2.get(v.upper())
        if hit:
            return hit
    return _COUNTRY_BY_KEY.get(_norm(v))


def country_display_names() -> dict[str, str]:
    """ISO2 -> display name for every known country (read-only copy)."""
    return {iso: c.name for iso, c in _COUNTRY_BY_ISO2.items()}


# --------------------------------------------------------------------------- chokepoints


@dataclass(frozen=True)
class Chokepoint:
    name: str
    latitude: float
    longitude: float
    region: str
    aliases: tuple[str, ...]


CHOKEPOINTS: tuple[Chokepoint, ...] = (
    Chokepoint(
        "Strait of Hormuz",
        26.57,
        56.25,
        "Middle East",
        ("Strait of Hormuz", "Hormuz Strait", "Straits of Hormuz", "Hormuz"),
    ),
    Chokepoint("Suez Canal", 30.46, 32.34, "Middle East", ("Suez Canal",)),
    Chokepoint(
        "Bab el-Mandeb",
        12.58,
        43.33,
        "Middle East",
        ("Bab el-Mandeb", "Bab al-Mandab", "Bab-el-Mandeb", "Bab el Mandeb", "Bab al Mandab"),
    ),
    Chokepoint(
        "Taiwan Strait",
        24.5,
        119.5,
        "East Asia",
        ("Taiwan Strait", "Strait of Taiwan", "Formosa Strait"),
    ),
    Chokepoint("Panama Canal", 9.08, -79.68, "Latin America", ("Panama Canal",)),
    Chokepoint(
        "Strait of Malacca",
        2.5,
        101.0,
        "Southeast Asia",
        ("Strait of Malacca", "Straits of Malacca", "Malacca Strait", "Malacca Straits"),
    ),
    Chokepoint(
        "Bosphorus",
        41.12,
        29.07,
        "Europe",
        ("Bosphorus", "Bosporus", "Bosphorus Strait", "Strait of Bosphorus"),
    ),
    Chokepoint("Dardanelles", 40.2, 26.4, "Europe", ("Dardanelles", "Strait of Dardanelles")),
    Chokepoint(
        "Strait of Gibraltar",
        35.96,
        -5.6,
        "Europe",
        ("Strait of Gibraltar", "Straits of Gibraltar"),
    ),
    Chokepoint("Cape of Good Hope", -34.36, 18.47, "Africa", ("Cape of Good Hope",)),
)

_CHOKE_BY_NAME: dict[str, Chokepoint] = {}
_CHOKE_PATTERNS: list[tuple[re.Pattern[str], Chokepoint]] = []
for _cp in CHOKEPOINTS:
    for _alias in (_cp.name, *_cp.aliases):
        _CHOKE_BY_NAME.setdefault(_norm(_alias), _cp)
        _CHOKE_PATTERNS.append(
            (re.compile(rf"(?<![a-z0-9]){re.escape(_norm(_alias))}(?![a-z0-9])"), _cp)
        )


def _first_chokepoint(texts: Iterable[str]) -> Chokepoint | None:
    """First chokepoint named in the earliest text that names any (earliest position within
    a text; gazetteer order breaks ties)."""
    for text in texts:
        n = _norm(text)
        if not n:
            continue
        best: tuple[int, Chokepoint] | None = None
        for pattern, cp in _CHOKE_PATTERNS:
            m = pattern.search(n)
            if m and (best is None or m.start() < best[0]):
                best = (m.start(), cp)
        if best:
            return best[1]
    return None


# --------------------------------------------------------------------------- normalize_geo


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    v = " ".join(value.split())
    return v or None


def _upstream_coords(raw: RawWorldEvent) -> tuple[float, float] | None:
    lat, lon = raw.latitude, raw.longitude
    if lat is None or lon is None:
        return None
    if not (math.isfinite(lat) and math.isfinite(lon)):
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return lat, lon


def _canonical_region(value: str | None) -> str | None:
    v = _clean(value)
    if v is None:
        return None
    return _REGION_ALIASES.get(_norm(v), v)


def _first_of_kind(entities: Sequence[Any], kind: str) -> list[Any]:
    return [e for e in entities if getattr(e, "kind", None) == kind]


def normalize_geo(raw: RawWorldEvent, entities: Sequence[EntityLike]) -> GeoInfo:
    ents = list(entities or [])

    # country: upstream first, then first resolvable country entity
    country = _lookup_country(raw.country, allow_iso2=True)
    if country is None:
        for e in _first_of_kind(ents, "country"):
            country = _lookup_country(getattr(e, "canonical", None), allow_iso2=False) or (
                _lookup_country(getattr(e, "raw", None), allow_iso2=False)
            )
            if country:
                break

    # chokepoint: only when actually named (entities, raw entity names, headline, body)
    texts: list[str] = [str(getattr(e, "canonical", "")) for e in ents]
    texts += [str(getattr(e, "raw", "") or "") for e in ents]
    texts += list(raw.entities)
    texts += [raw.headline, raw.body or ""]
    chokepoint = _first_chokepoint(texts)

    # city
    city = _clean(raw.city)
    if city is None:
        for e in _first_of_kind(ents, "city"):
            city = _clean(getattr(e, "canonical", None))
            if city:
                break

    # region: upstream > country table > region entity > chokepoint
    region = _canonical_region(raw.region)
    if region is None and country is not None:
        region = country.region
    if region is None:
        for e in _first_of_kind(ents, "region"):
            region = _canonical_region(getattr(e, "canonical", None))
            if region:
                break
    if region is None and chokepoint is not None:
        region = chokepoint.region

    # coordinates: upstream preserved exactly; chokepoint fills only when absent
    coords = _upstream_coords(raw)
    if coords is None and chokepoint is not None:
        coords = (chokepoint.latitude, chokepoint.longitude)

    resolved = any(v is not None for v in (country, region, city, coords, chokepoint))
    if not resolved:
        return GeoInfo(resolved=False)
    return GeoInfo(
        country=country.iso2 if country else None,
        country_name=country.name if country else None,
        region=region,
        city=city,
        latitude=coords[0] if coords else None,
        longitude=coords[1] if coords else None,
        chokepoint=chokepoint.name if chokepoint else None,
        resolved=True,
    )


# --------------------------------------------------------------------------- location_key


def location_key(geo: GeoInfo) -> str:
    """Stable lowercase-slug key: chokepoint > city > country > region > 'unknown'."""
    if geo.chokepoint and _slug(geo.chokepoint):
        known = _CHOKE_BY_NAME.get(_norm(geo.chokepoint))
        return f"chokepoint:{_slug(known.name if known else geo.chokepoint)}"
    country_slug = _slug(geo.country) if geo.country else ""
    if geo.city and _slug(geo.city):
        return (
            f"city:{country_slug}:{_slug(geo.city)}"
            if country_slug
            else (f"city:{_slug(geo.city)}")
        )
    if country_slug:
        return f"country:{country_slug}"
    if geo.country_name and _slug(geo.country_name):
        known_c = _lookup_country(geo.country_name, allow_iso2=False)
        return (
            f"country:{known_c.iso2.lower()}" if known_c else f"country:{_slug(geo.country_name)}"
        )
    if geo.region and _slug(geo.region):
        return f"region:{_slug(geo.region)}"
    return "unknown"
