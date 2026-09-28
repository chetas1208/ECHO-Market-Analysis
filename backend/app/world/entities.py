"""Deterministic entity normalization and extraction for world events (no ML, no network).

Public API
- ``normalize_entity(name)``: alias table lookup -> ``NormalizedEntity`` or ``None`` (unknown).
- ``extract_entities(raw)``: provider-supplied entities/country/region/city first (in that
  order), then a longest-match dictionary scan of headline and body; de-duplicated by canonical
  name, stable order (provider order, then first appearance in the headline, then the body).
- ``COMPANY_TICKERS``: canonical company name -> ticker for every tracked company in
  ``config/universe.yaml``.

Matching rules (documented because they are the whole "model")
- Matching is done on a *matching key* only: NFKD-folded, casefolded, punctuation/hyphens
  collapsed, leading "the" dropped. Canonical names are never altered by that folding, and
  trailing corporate suffixes (Inc., Corp., Ltd., Co., plc, ...) are stripped for matching only.
- Text scan is one regex with alternatives ordered longest-alias-first, so at any position the
  longest alias wins ("Strait of Hormuz" beats "Hormuz", "Taiwan Strait" beats "Taiwan") and
  matches never overlap. Matches need word boundaries on both sides.
- Short acronyms (<= 6 upper-case chars, e.g. UK, EU, WTI, OPEC) and a few ambiguous words
  (Fed, Meta, Apple, Chad, ...) are CASE-SENSITIVE in free text. The pronoun "us" is never
  matched: only "US"/"U.S."/"USA"/"United States" count, and bare "US" (and bare tickers, "SEC")
  is ignored inside all-caps text where it cannot be told apart from the pronoun.
- Ambiguous tickers (COP, MU, GS, META, ...) resolve in ``normalize_entity`` but are not scanned
  in free text. "LNG" means liquefied natural gas (commodity), never Cheniere.
- Unknown provider entities are kept as kind ``other`` (verbatim, whitespace-collapsed); nothing
  is dropped and nothing is invented. Provider country/region/city fields use their field kind
  when the value is not in the tables.
- Limitations: no coreference, no demonyms ("Chinese"), no disambiguation by context.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Final

from app.world.types import NormalizedEntity, RawWorldEvent

__all__ = ["COMPANY_TICKERS", "extract_entities", "normalize_entity"]

# --------------------------------------------------------------------------------------
# Alias tables. Alias strings are "|"-separated. The canonical name is always an alias.
# Prefix "!" forces case-sensitive scan matching, "~" forces case-insensitive.
# --------------------------------------------------------------------------------------

# (canonical, ISO 3166-1 alpha-2, aliases)
_COUNTRIES: Final[tuple[tuple[str, str, str], ...]] = (
    ("United States", "US", "US|U.S.|USA|U.S.A.|United States of America|America"),
    ("United Kingdom", "GB", "UK|U.K.|Great Britain|Britain"),
    ("United Arab Emirates", "AE", "UAE|U.A.E."),
    ("Russia", "RU", "Russian Federation"),
    ("China", "CN", "PRC|People's Republic of China|Mainland China"),
    ("Taiwan", "TW", "ROC|Republic of China|Chinese Taipei"),
    ("Hong Kong", "HK", "Hong Kong SAR"),
    ("Japan", "JP", ""),
    ("South Korea", "KR", "Republic of Korea|ROK|S. Korea"),
    ("North Korea", "KP", "DPRK|N. Korea|Democratic People's Republic of Korea"),
    ("India", "IN", ""),
    ("Pakistan", "PK", ""),
    ("Bangladesh", "BD", ""),
    ("Vietnam", "VN", "Viet Nam"),
    ("Thailand", "TH", ""),
    ("Malaysia", "MY", ""),
    ("Singapore", "SG", ""),
    ("Indonesia", "ID", ""),
    ("Philippines", "PH", ""),
    ("Cambodia", "KH", ""),
    ("Myanmar", "MM", "Burma"),
    ("Sri Lanka", "LK", ""),
    ("Afghanistan", "AF", ""),
    ("Kazakhstan", "KZ", ""),
    ("Uzbekistan", "UZ", ""),
    ("Azerbaijan", "AZ", ""),
    ("Armenia", "AM", ""),
    ("Australia", "AU", ""),
    ("New Zealand", "NZ", ""),
    ("Iran", "IR", "Islamic Republic of Iran"),
    ("Iraq", "IQ", ""),
    ("Israel", "IL", ""),
    ("Palestine", "PS", "State of Palestine|Palestinian Territories"),
    ("Saudi Arabia", "SA", "KSA|Kingdom of Saudi Arabia"),
    ("Qatar", "QA", ""),
    ("Kuwait", "KW", ""),
    ("Oman", "OM", ""),
    ("Bahrain", "BH", ""),
    ("Yemen", "YE", ""),
    ("Syria", "SY", ""),
    ("Lebanon", "LB", ""),
    ("Jordan", "JO", "!Jordan"),
    ("Egypt", "EG", ""),
    ("Turkey", "TR", "!Turkey|Türkiye|Turkiye"),
    ("Ukraine", "UA", ""),
    ("Belarus", "BY", ""),
    ("Germany", "DE", ""),
    ("France", "FR", ""),
    ("Italy", "IT", ""),
    ("Spain", "ES", ""),
    ("Netherlands", "NL", "Holland"),
    ("Belgium", "BE", ""),
    ("Poland", "PL", ""),
    ("Sweden", "SE", ""),
    ("Norway", "NO", ""),
    ("Finland", "FI", ""),
    ("Denmark", "DK", ""),
    ("Switzerland", "CH", ""),
    ("Greece", "GR", ""),
    ("Romania", "RO", ""),
    ("Hungary", "HU", ""),
    ("Czech Republic", "CZ", "Czechia"),
    ("Greenland", "GL", ""),
    ("Canada", "CA", ""),
    ("Mexico", "MX", ""),
    ("Panama", "PA", ""),
    ("Cuba", "CU", ""),
    ("Brazil", "BR", ""),
    ("Argentina", "AR", ""),
    ("Chile", "CL", ""),
    ("Peru", "PE", ""),
    ("Colombia", "CO", ""),
    ("Venezuela", "VE", ""),
    ("Ecuador", "EC", ""),
    ("South Africa", "ZA", ""),
    ("Nigeria", "NG", ""),
    ("Libya", "LY", ""),
    ("Ethiopia", "ET", ""),
    ("Sudan", "SD", ""),
    ("South Sudan", "SS", ""),
    ("Kenya", "KE", ""),
    ("Algeria", "DZ", ""),
    ("Morocco", "MA", ""),
    ("Angola", "AO", ""),
    ("Somalia", "SO", ""),
    ("Djibouti", "DJ", ""),
    ("Eritrea", "ER", ""),
    ("Chad", "TD", "!Chad"),
    ("Niger", "NE", "!Niger"),
    ("Democratic Republic of the Congo", "CD", "DR Congo|DRC"),
)

# (canonical, aliases)
_REGIONS: Final[tuple[tuple[str, str], ...]] = (
    ("Middle East", "Mideast"),
    ("Persian Gulf", "Arabian Gulf"),
    ("Gulf of Oman", ""),
    ("Gulf of Aden", ""),
    ("Gulf of Mexico", ""),
    ("Red Sea", ""),
    ("Black Sea", ""),
    ("Baltic Sea", ""),
    ("Mediterranean Sea", "Mediterranean"),
    ("Arabian Sea", ""),
    ("South China Sea", ""),
    ("East China Sea", ""),
    ("Sea of Japan", ""),
    ("Indian Ocean", ""),
    ("Pacific Ocean", ""),
    ("Atlantic Ocean", ""),
    ("Arctic", ""),
    ("Horn of Africa", ""),
    ("Sahel", ""),
    ("Africa", ""),
    ("Europe", ""),
    ("Eastern Europe", ""),
    ("Western Europe", ""),
    ("Scandinavia", ""),
    ("Balkans", ""),
    ("Caucasus", ""),
    ("Eurozone", "Euro area"),
    ("Asia", ""),
    ("Asia-Pacific", "Asia Pacific|APAC"),
    ("Southeast Asia", ""),
    ("East Asia", ""),
    ("South Asia", ""),
    ("Central Asia", ""),
    ("Korean Peninsula", ""),
    ("North America", ""),
    ("Latin America", ""),
    ("South America", ""),
    ("Caribbean", ""),
    ("Oceania", ""),
    ("Gaza Strip", "Gaza"),
    ("West Bank", ""),
    ("Kashmir", ""),
    ("Crimea", ""),
    ("Donbas", "Donbass"),
    ("Xinjiang", ""),
)

_CITIES: Final[tuple[tuple[str, str], ...]] = (
    ("Taipei", ""),
    ("Hsinchu", ""),
    ("Kaohsiung", ""),
    ("Shanghai", ""),
    ("Beijing", ""),
    ("Shenzhen", ""),
    ("Tokyo", ""),
    ("Seoul", ""),
    ("Mumbai", ""),
    ("New Delhi", ""),
    ("Moscow", ""),
    ("Kyiv", "Kiev"),
    ("Tehran", ""),
    ("Baghdad", ""),
    ("Riyadh", ""),
    ("Dubai", ""),
    ("Abu Dhabi", ""),
    ("Doha", ""),
    ("Jeddah", ""),
    ("Jerusalem", ""),
    ("Tel Aviv", ""),
    ("Istanbul", ""),
    ("Cairo", ""),
    ("London", ""),
    ("Rotterdam", ""),
    ("New York", ""),
    ("Houston", ""),
    ("Los Angeles", ""),
)

_COMMODITIES: Final[tuple[tuple[str, str], ...]] = (
    (
        "crude oil",
        "crude|Brent|Brent crude|WTI|West Texas Intermediate|oil price|oil prices|oil supply"
        "|oil supplies|oil output|oil production|oil exports|oil market|oil markets",
    ),
    ("natural gas", "nat gas|Henry Hub|TTF"),
    ("liquefied natural gas", "LNG"),
    ("gasoline", "petrol"),
    ("diesel", ""),
    ("jet fuel", ""),
    ("coal", ""),
    ("uranium", ""),
    ("copper", ""),
    ("aluminum", "aluminium"),
    ("lithium", ""),
    ("cobalt", ""),
    ("nickel", ""),
    ("iron ore", ""),
    ("steel", ""),
    ("gold", ""),
    ("silver", ""),
    ("platinum", ""),
    ("palladium", ""),
    ("rare earths", "rare earth|rare earth elements"),
    ("wheat", ""),
    ("corn", ""),
    ("soybeans", "soybean|soya"),
    ("sugar", ""),
    ("coffee", ""),
    ("cocoa", ""),
    ("cotton", ""),
    ("palm oil", ""),
    ("fertilizer", "fertiliser|fertilizers|fertilisers"),
)

_INFRASTRUCTURE: Final[tuple[tuple[str, str], ...]] = (
    ("Strait of Hormuz", "Hormuz|Hormuz Strait|Straits of Hormuz"),
    ("Suez Canal", "Suez"),
    ("Bab el-Mandeb", "Bab al-Mandab|Bab al-Mandeb|Bab el-Mandab|Bab el Mandeb"),
    ("Taiwan Strait", "Formosa Strait|Strait of Taiwan"),
    ("Panama Canal", ""),
    ("Strait of Malacca", "Malacca Strait|Straits of Malacca|Malacca"),
    ("Strait of Gibraltar", "Gibraltar Strait"),
    ("Bosphorus", "Bosporus|Bosphorus Strait|Turkish Straits"),
    ("Dardanelles", ""),
    ("Kerch Strait", ""),
    ("Lombok Strait", ""),
    ("Sunda Strait", ""),
    ("Danish Straits", ""),
    ("Cape of Good Hope", ""),
    ("Port of Shanghai", "Shanghai port"),
    ("Port of Singapore", "Singapore port"),
    ("Port of Rotterdam", "Rotterdam port"),
    ("Port of Los Angeles", ""),
    ("Port of Long Beach", ""),
    ("Port of Ningbo", "Ningbo-Zhoushan"),
    ("Port of Shenzhen", ""),
    ("Port of Busan", ""),
    ("Port of Hamburg", ""),
    ("Port of Antwerp", ""),
    ("Port of Houston", ""),
    ("Port of Kaohsiung", ""),
    ("Port of Jebel Ali", "Jebel Ali"),
    ("Port of Fujairah", "Fujairah"),
    ("Port of Odesa", "Port of Odessa"),
    ("Ras Tanura", ""),
    ("Abqaiq", ""),
    ("Kharg Island", ""),
    ("Yanbu", ""),
    ("Nord Stream", "Nord Stream 1|Nord Stream 2"),
    ("Druzhba pipeline", "Druzhba"),
    ("Colonial Pipeline", ""),
    ("Hsinchu Science Park", ""),
    ("TSMC fabs", "TSMC fab|TSMC's fabs|TSMC's fab"),
    (
        "subsea cables",
        "subsea cable|undersea cable|undersea cables|submarine cable|submarine cables",
    ),
)

_ORGANIZATIONS: Final[tuple[tuple[str, str], ...]] = (
    ("OPEC", "~OPEC|Organization of the Petroleum Exporting Countries"),
    ("OPEC+", "!OPEC+"),
    ("NATO", "~NATO|North Atlantic Treaty Organization"),
    ("European Union", "EU"),
    ("United Nations", "UN"),
    ("World Trade Organization", "WTO"),
    ("International Monetary Fund", "IMF"),
    ("World Bank", ""),
    ("World Health Organization", ""),
    ("International Energy Agency", "IEA"),
    ("OECD", ""),
    ("BRICS", ""),
    ("ASEAN", ""),
    ("G7", ""),
    ("G20", ""),
    ("Gulf Cooperation Council", "GCC"),
    ("European Commission", ""),
    ("Federal Reserve", "!Fed|FOMC|Federal Open Market Committee"),
    ("European Central Bank", "ECB"),
    ("Bank of England", "BoE"),
    ("Bank of Japan", "BoJ"),
    ("People's Bank of China", "PBOC|PBoC"),
    ("Securities and Exchange Commission", "SEC"),
    ("OFAC", "Office of Foreign Assets Control"),
    ("Houthis", "Houthi"),
    ("Hamas", ""),
    ("Hezbollah", ""),
    ("IRGC", "Islamic Revolutionary Guard Corps|Revolutionary Guards"),
)

# (canonical, ticker or None, aliases). Tickers here are exactly the equities in universe.yaml.
_COMPANIES: Final[tuple[tuple[str, str | None, str], ...]] = (
    ("NVIDIA", "NVDA", "Nvidia"),
    ("AMD", "AMD", "Advanced Micro Devices"),
    ("Broadcom", "AVGO", ""),
    (
        "TSMC",
        "TSM",
        "Taiwan Semiconductor|Taiwan Semiconductor Manufacturing"
        "|Taiwan Semiconductor Manufacturing Company",
    ),
    ("Intel", "INTC", "!Intel"),
    ("Qualcomm", "QCOM", ""),
    ("Micron Technology", "MU", "!Micron"),
    ("Microsoft", "MSFT", ""),
    ("Amazon", "AMZN", "!Amazon|Amazon.com"),
    ("Alphabet", "GOOGL", "!Alphabet|Google"),
    ("Meta Platforms", "META", "!Meta"),
    ("Apple", "AAPL", "!Apple"),
    ("ExxonMobil", "XOM", "Exxon Mobil|Exxon"),
    ("Chevron", "CVX", ""),
    ("ConocoPhillips", "COP", "Conoco Phillips"),
    ("SLB", "SLB", "Schlumberger"),
    ("Cheniere Energy", "LNG", "Cheniere"),
    ("Delta Air Lines", "DAL", "Delta Airlines|Delta Air"),
    ("United Airlines", "UAL", "United Airlines Holdings"),
    ("American Airlines", "AAL", "American Airlines Group"),
    ("Southwest Airlines", "LUV", ""),
    ("Lockheed Martin", "LMT", ""),
    ("RTX", "RTX", "Raytheon|Raytheon Technologies"),
    ("Northrop Grumman", "NOC", ""),
    ("CrowdStrike", "CRWD", ""),
    ("Palo Alto Networks", "PANW", ""),
    ("JPMorgan Chase", "JPM", "JPMorgan|JP Morgan|J.P. Morgan"),
    ("Bank of America", "BAC", "BofA"),
    ("Goldman Sachs", "GS", "Goldman Sachs Group"),
    # Sub-brands relevant to outage/infrastructure events (no ticker of their own).
    ("Amazon Web Services", None, "AWS"),
    ("Microsoft Azure", None, ""),
    ("Google Cloud", None, "Google Cloud Platform"),
)

COMPANY_TICKERS: Final[dict[str, str]] = {c: t for c, t, _ in _COMPANIES if t is not None}

# Tickers too ambiguous to scan in free text (still resolved by normalize_entity).
_AMBIGUOUS_TICKERS: Final[frozenset[str]] = frozenset(
    {"COP", "MU", "GS", "META", "LUV", "DAL", "AAL"}
)
# Bare aliases ignored inside all-caps text (cannot be told from words/pronouns there).
_ALLCAPS_GUARD: Final[frozenset[str]] = frozenset({"US", "SEC"})
# Aliases that only match with exactly this spelling, even in normalize_entity.
_STRICT: Final[frozenset[str]] = frozenset({"US", "U.S.", "Fed", "Chad"})
# "LNG" is the commodity, not the Cheniere ticker.
_TICKER_SKIP: Final[frozenset[str]] = frozenset({"LNG"})

_CORP_SUFFIXES: Final[str] = r"inc|corp|corporation|co|ltd|limited|plc|company"
_SUFFIX_TAIL: Final = re.compile(rf"(?:[\s,]+&)?[\s,]+(?:{_CORP_SUFFIXES})\.?$", re.IGNORECASE)
_SUFFIX_SCAN: Final[str] = rf"(?:(?:[\s,]+&)?[\s,]+(?:{_CORP_SUFFIXES})(?!\w)\.?)?"


# --------------------------------------------------------------------------------------
# Matching helpers
# --------------------------------------------------------------------------------------


def _key(text: str) -> str:
    """Matching key: fold accents/case/punctuation. Used for lookup only, never for output."""
    s = unicodedata.normalize("NFKD", text)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.casefold().replace("&", " and ")
    s = re.sub(r"[-_/\u2013\u2014]", " ", s)
    s = re.sub(r"[^\w\s+]", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    if s.startswith("the "):
        s = s[4:]
    return s


def _prep(text: str) -> str:
    """Normalize typographic characters in free text before scanning."""
    t = unicodedata.normalize("NFKC", text)
    return (
        t.replace("\u2019", "'")
        .replace("\u2018", "'")
        .replace("\u2013", "-")
        .replace("\u2014", "-")
    )


def _collapse(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _is_upper(text: str) -> bool:
    return any(c.isalpha() for c in text) and not any(c.islower() for c in text)


@dataclass(frozen=True, slots=True)
class _Alias:
    text: str
    canonical: str
    kind: str
    cs: bool  # case-sensitive in free-text scan
    guard: bool  # skipped in all-caps text
    scan: bool  # participates in free-text scan
    company: bool  # optional corporate suffix allowed in scan


_ALIASES: list[_Alias] = []
_BY_EXACT: dict[str, _Alias] = {}
_BY_KEY: dict[str, _Alias] = {}


def _register(
    canonical: str,
    kind: str,
    aliases: str,
    *,
    company: bool = False,
    ticker: str | None = None,
) -> None:
    flags: dict[str, bool | None] = {}
    for raw in [canonical, *[a for a in aliases.split("|") if a]]:
        text, forced = (raw[1:], raw[0] == "!") if raw[0] in "!~" else (raw, None)
        if text not in flags or forced is not None:  # explicit !/~ overrides the default
            flags[text] = forced
    items = list(flags.items())
    guards: set[str] = set()
    noscan: set[str] = set()
    if ticker and ticker not in _TICKER_SKIP and all(t != ticker for t, _ in items):
        items.append((ticker, True))
        guards.add(ticker)
        if ticker in _AMBIGUOUS_TICKERS:
            noscan.add(ticker)
    for text, force_cs in items:
        cs = force_cs if force_cs is not None else (_is_upper(text) and len(text) <= 6)
        alias = _Alias(
            text=text,
            canonical=canonical,
            kind=kind,
            cs=cs,
            guard=text in guards or text in _ALLCAPS_GUARD,
            scan=text not in noscan,
            company=company,
        )
        prev = _BY_EXACT.get(text)
        if prev is not None:
            if prev.canonical != canonical:
                raise ValueError(f"alias {text!r} maps to {prev.canonical!r} and {canonical!r}")
            continue
        _BY_EXACT[text] = alias
        _ALIASES.append(alias)
        if text in _STRICT:
            continue
        k = _key(text)
        other = _BY_KEY.get(k)
        if other is not None and other.canonical != canonical:
            raise ValueError(f"key {k!r} maps to {other.canonical!r} and {canonical!r}")
        _BY_KEY.setdefault(k, alias)


for _c, _iso, _a in _COUNTRIES:
    _register(_c, "country", _a)
for _c, _a in _REGIONS:
    _register(_c, "region", _a)
for _c, _a in _CITIES:
    _register(_c, "city", _a)
for _c, _a in _COMMODITIES:
    _register(_c, "commodity", _a)
for _c, _a in _INFRASTRUCTURE:
    _register(_c, "infrastructure", _a)
for _c, _a in _ORGANIZATIONS:
    _register(_c, "organization", _a)
for _c, _t, _a in _COMPANIES:
    _register(_c, "company", _a, company=True, ticker=_t)

_ISO2: Final[dict[str, str]] = {iso: c for c, iso, _ in _COUNTRIES}

# Free-text scan dictionaries (only aliases with scan=True).
_SCAN_EXACT: Final[dict[str, _Alias]] = {a.text: a for a in _ALIASES if a.scan and a.cs}
_SCAN_CI: Final[dict[str, _Alias]] = {_key(a.text): a for a in _ALIASES if a.scan and not a.cs}


def _flex(text: str) -> str:
    parts = re.split(r"[\s\-]+", text.strip())
    return r"[\s\-]+".join(re.escape(p) for p in parts)


def _build_scan_regex() -> re.Pattern[str]:
    alts: list[str] = []
    for a in sorted((x for x in _ALIASES if x.scan), key=lambda x: (-len(x.text), x.text)):
        body = _flex(a.text) + (_SUFFIX_SCAN if a.company else "")
        alts.append(body if a.cs else f"(?i:{body})")
    return re.compile(r"(?<!\w)(?:" + "|".join(alts) + r")(?!\w)")


_SCAN_RE: Final = _build_scan_regex()


def _candidates(text: str) -> Iterator[str]:
    """Yield the string, then the string with trailing corporate suffixes stripped."""
    s = text.strip()
    if s.lower().startswith("the "):
        yield s
        s = s[4:].strip()
    yield s
    while True:
        t = s.rstrip(" ,;")
        m = _SUFFIX_TAIL.search(t)
        if m is None or m.start() == 0:
            return
        s = t[: m.start()]
        yield s


def _lookup(name: str) -> _Alias | None:
    for cand in _candidates(name):
        hit = _BY_EXACT.get(cand) or _BY_KEY.get(_key(cand))
        if hit is not None:
            return hit
    return None


def _entity(alias: _Alias, raw: str) -> NormalizedEntity:
    return NormalizedEntity(canonical=alias.canonical, kind=alias.kind, raw=raw)


def normalize_entity(name: str) -> NormalizedEntity | None:
    """Map a raw name to its canonical entity, or ``None`` when unknown/empty.

    ``raw`` on the result is the input, whitespace-collapsed. A leading ``$`` (cashtag) is
    accepted for tickers. The pronoun "us" (lower case) never resolves.
    """
    if not isinstance(name, str):
        return None
    raw = _collapse(name)
    if not raw:
        return None
    probe = raw[1:].strip() if raw.startswith("$") else raw
    if not probe:
        return None
    alias = _lookup(probe)
    return _entity(alias, raw) if alias is not None else None


def _scan(text: str | None) -> list[NormalizedEntity]:
    if not text:
        return []
    t = _prep(text)
    allcaps = _is_upper(t)
    out: list[NormalizedEntity] = []
    for m in _SCAN_RE.finditer(t):
        found = m.group(0)
        alias: _Alias | None = None
        for cand in _candidates(found):
            alias = _SCAN_EXACT.get(cand) or _SCAN_CI.get(_key(cand))
            if alias is not None:
                break
        if alias is None or (allcaps and alias.guard):
            continue
        out.append(_entity(alias, _collapse(found)))
    return out


def _provider_entity(value: str | None, field_kind: str) -> NormalizedEntity | None:
    if value is None:
        return None
    raw = _collapse(value)
    if not raw:
        return None
    hit = normalize_entity(raw)
    if hit is not None:
        return hit
    if field_kind == "country" and len(raw) == 2 and raw.isalpha():
        country = _ISO2.get(raw.upper())
        if country is not None:
            return NormalizedEntity(canonical=country, kind="country", raw=raw)
    return NormalizedEntity(canonical=raw, kind=field_kind, raw=raw)


def extract_entities(raw: RawWorldEvent) -> list[NormalizedEntity]:
    """Entities for one event: provider-supplied first, then dictionary scan; de-duplicated.

    Order: ``raw.entities`` (given order), ``country``, ``region``, ``city``, then matches in
    the headline (text order), then the body. De-duplication is by canonical name (first
    occurrence wins, so a provider-supplied entity keeps its raw spelling).
    """
    candidates: list[NormalizedEntity] = []
    for name in raw.entities:
        hit = _provider_entity(name, "other")
        if hit is not None:
            candidates.append(hit)
    for value, field_kind in ((raw.country, "country"), (raw.region, "region"), (raw.city, "city")):
        hit = _provider_entity(value, field_kind)
        if hit is not None:
            candidates.append(hit)
    candidates.extend(_scan(raw.headline))
    candidates.extend(_scan(raw.body))

    seen: set[str] = set()
    result: list[NormalizedEntity] = []
    for ent in candidates:
        dedup_key = _key(ent.canonical) or ent.canonical
        if dedup_key in seen:
            continue
        seen.add(dedup_key)
        result.append(ent)
    return result
