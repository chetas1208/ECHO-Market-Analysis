"""Deterministic event fingerprinting and same-event matching (no ML, no wall clock).

``event_fingerprint`` gives a coarse, stable hash used as a fast identity key. Because time is
bucketed, two near-identical reports straddling a bucket edge get different fingerprints, so
``is_same_event`` also merges on entity/location overlap + time window + headline similarity.

Heuristic limits: token similarity is bag-of-words with very light stemming; it cannot tell
apart two genuinely distinct events described with the same words. A small set of
distinguishing tokens (``aftershock``, ``second``, ``new``) that appears on exactly one side
blocks a merge.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.world.geo import location_key as _geo_key
from app.world.settings import DedupConfig
from app.world.types import GeoInfo

# Entity kinds that participate in fingerprint / overlap keys.
FINGERPRINT_ENTITY_KINDS: frozenset[str] = frozenset(
    {"country", "region", "infrastructure", "company", "organization"}
)

# Classes that may describe the same underlying event from different angles.
_CLASS_FAMILIES: dict[str, str] = {
    "shipping_disruption": "shipping_port",
    "port_disruption": "shipping_port",
    "energy_supply_disruption": "energy_commodity",
    "commodity_shock": "energy_commodity",
    "cyber_incident": "cyber_outage",
    "infrastructure_outage": "cyber_outage",
}

# Present on exactly one side => different events (follow-ups are new information).
DISTINGUISHING_TOKENS: frozenset[str] = frozenset({"aftershock", "second", "new"})

_STOPWORD_TEXT = (
    "a an and are as at be been but by for from has have had he her his in into is it its of "
    "on or over per she that the their them they this to was were will with within without "
    "after before during amid against about than then there these those which who whom while "
    "also not no if so up out off says say said report reports reported reportedly update "
    "updates updated breaking news live latest just now today yesterday"
)
_STOPWORDS: frozenset[str] = frozenset(w for w in _STOPWORD_TEXT.split(" ") if w)

_APOS_S = re.compile("['\u2019]s\\b")
_WORD = re.compile(r"[^\W_]+", re.UNICODE)
_VOWELS = frozenset("aeiou")


def _value(x: Any) -> str:
    return str(getattr(x, "value", x))


def _aware(dt: datetime) -> datetime:
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def time_bucket(occurred_at: datetime, dedup: DedupConfig) -> int:
    """floor(epoch_hours / time_bucket_hours)."""
    hours = _aware(occurred_at).timestamp() / 3600.0
    return int(hours // dedup.time_bucket_hours)


def entity_keys(entities: Any) -> frozenset[str]:
    """Casefolded canonical names of fingerprint-relevant entities (duck-typed)."""
    out: set[str] = set()
    for e in entities or ():
        if _value(getattr(e, "kind", "")).casefold() in FINGERPRINT_ENTITY_KINDS:
            name = str(getattr(e, "canonical", "")).strip().casefold()
            if name:
                out.add(name)
    return frozenset(out)


def geo_location_key(geo: Any) -> str:
    """Stable location key; delegates to ``geo.location_key`` so both always agree."""
    if geo is None:
        return "unknown"
    if not isinstance(geo, GeoInfo):  # duck-typed input
        geo = GeoInfo(
            **{
                f: getattr(geo, f, None)
                for f in ("country", "country_name", "region", "city", "chokepoint")
            }
        )
    return _geo_key(geo)


def _digest(event_class: Any, keys: frozenset[str], loc: str, bucket: int) -> str:
    raw = f"{_value(event_class)}|{','.join(sorted(keys))}|{loc}|{bucket}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def event_fingerprint(
    event_class: Any, entities: Any, geo: Any, occurred_at: datetime, dedup: DedupConfig
) -> str:
    """sha1 hex of ``class|sorted entity keys|location_key|time_bucket``."""
    return _digest(
        event_class, entity_keys(entities), geo_location_key(geo), time_bucket(occurred_at, dedup)
    )


def _stem(w: str) -> str:
    if len(w) > 4 and w.endswith("ies"):
        w = w[:-3] + "y"
    elif len(w) > 4 and w.endswith("sses"):
        w = w[:-2]
    elif len(w) > 3 and w.endswith("s") and not w.endswith(("ss", "us", "is")):
        w = w[:-1]
    if len(w) > 5 and w.endswith("ing") and _VOWELS & set(w[:-3]):
        w = w[:-3]
    elif len(w) > 4 and w.endswith("ed") and _VOWELS & set(w[:-2]):
        w = w[:-2]
    if len(w) > 3 and w[-1] == w[-2] and w[-1] not in _VOWELS and w[-1] not in "lsz":
        w = w[:-1]
    if len(w) > 3 and w.endswith("e"):
        w = w[:-1]
    return w


def text_tokens(headline: str) -> frozenset[str]:
    """Lowercase, strip punctuation, drop stopwords/numbers/1-char tokens, light stemming."""
    if not headline:
        return frozenset()
    text = unicodedata.normalize("NFKC", headline).casefold()
    text = _APOS_S.sub("", text)
    out: set[str] = set()
    for w in _WORD.findall(text):
        if len(w) < 2 or w.isdigit() or w in _STOPWORDS:
            continue
        s = _stem(w)
        if len(s) >= 2 and s not in _STOPWORDS:
            out.add(s)
    return frozenset(out)


def text_similarity(a: frozenset[str], b: frozenset[str]) -> float:
    """max(Jaccard, containment) in [0,1]; 0.0 when either side is empty."""
    if not a or not b:
        return 0.0
    inter = len(a & b)
    if inter == 0:
        return 0.0
    return max(inter / len(a | b), inter / min(len(a), len(b)))


@dataclass(frozen=True)
class EventKey:
    event_class: Any  # EventClass | str
    entity_keys: frozenset[str]
    location_key: str
    occurred_at: datetime
    tokens: frozenset[str]


def _family(event_class: Any) -> str:
    v = _value(event_class)
    return _CLASS_FAMILIES.get(v, v)


def is_same_event(a: EventKey, b: EventKey, dedup: DedupConfig) -> tuple[bool, float, str]:
    """Decide whether two keys describe the same event -> (same, score in [0,1], reason)."""
    sim = text_similarity(a.tokens, b.tokens)

    distinct = (a.tokens ^ b.tokens) & DISTINGUISHING_TOKENS
    if distinct:
        return False, sim, f"distinguishing_token:{','.join(sorted(distinct))}"

    fp_a = _digest(a.event_class, a.entity_keys, a.location_key, time_bucket(a.occurred_at, dedup))
    fp_b = _digest(b.event_class, b.entity_keys, b.location_key, time_bucket(b.occurred_at, dedup))
    if fp_a == fp_b:
        return True, 1.0, "identical_fingerprint"

    if _value(a.event_class) != _value(b.event_class) and _family(a.event_class) != _family(
        b.event_class
    ):
        return False, sim, "class_mismatch"

    shared = a.entity_keys & b.entity_keys
    same_loc = a.location_key == b.location_key and a.location_key not in ("", "unknown")
    if not shared and not same_loc:
        return False, sim, "no_entity_or_location_overlap"

    gap_h = abs((_aware(a.occurred_at) - _aware(b.occurred_at)).total_seconds()) / 3600.0
    if gap_h > dedup.max_merge_window_hours:
        return False, sim, f"outside_merge_window:{gap_h:.1f}h"

    if not a.tokens or not b.tokens:
        return False, 0.0, "no_text_tokens"
    if sim < dedup.text_similarity_threshold:
        return False, sim, f"text_similarity_below_threshold:{sim:.2f}"

    basis = "entity" if shared else "location"
    return True, sim, f"similar_text:{sim:.2f}+{basis}_overlap+within_{gap_h:.1f}h"
