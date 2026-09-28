"""Financial text analysis contract: result model, status, protocol, null + caching wrappers.

This module is deliberately dependency-light: it never imports torch / transformers. Concrete
model-backed analyzers (e.g. ``modernfinbert.ModernFinBERTAnalyzer``) live in sibling modules and
satisfy the :class:`FinancialTextAnalyzer` protocol.

Scope guard: a financial sentiment model is ONLY meaningful on company / market text (earnings,
analyst calls, deals, central-bank news). It must never be used as a geopolitical reasoner.
:func:`is_financial_text` is a deterministic keyword gate callers use to decide whether to run the
model at all.

Contract: ``analyze`` never raises and returns ``None`` whenever no analysis is available.
"""

from __future__ import annotations

import hashlib
import re
import threading
from collections import OrderedDict
from enum import StrEnum
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field


class AnalyzerStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    LOADING = "LOADING"
    UNAVAILABLE = "UNAVAILABLE"
    DISABLED = "DISABLED"


class TextAnalysis(BaseModel):
    """Sentiment of a financial text. Scores are model outputs, not probabilities of outcomes."""

    label: Literal["positive", "negative", "neutral"]
    scores: dict[str, float] = Field(default_factory=dict)
    model: str
    latency_ms: float | None = None


@runtime_checkable
class FinancialTextAnalyzer(Protocol):
    status: AnalyzerStatus

    def analyze(self, text: str) -> TextAnalysis | None:
        """Return the analysis, or ``None`` when unavailable. Must never raise."""
        ...


class NullAnalyzer:
    """Analyzer that is switched off: status DISABLED, always returns ``None``."""

    status: AnalyzerStatus = AnalyzerStatus.DISABLED

    def analyze(self, text: str) -> TextAnalysis | None:
        return None


_MISS: Any = object()


def _cache_key(text: str) -> str:
    return hashlib.sha256(text.strip().encode("utf-8", errors="replace")).hexdigest()


class CachingAnalyzer:
    """Bounded, thread-safe LRU cache in front of another analyzer.

    - Key: ``sha256(text.strip())``.
    - Successful results are always cached.
    - A ``None`` result is cached ONLY when the inner analyzer is DISABLED (a permanent state).
      For UNAVAILABLE / LOADING / AVAILABLE-but-failed the miss is NOT cached, so recovery
      (model finishes loading, a transient failure clears) is picked up on the next call.
    - ``hits`` / ``misses`` count cache lookups. The inner analyzer runs outside the lock.
    - ``status`` is delegated to the inner analyzer.
    - ``analyze`` never raises: inner exceptions become ``None`` (and are not cached).
    """

    def __init__(self, inner: FinancialTextAnalyzer, max_items: int = 2048) -> None:
        self._inner = inner
        self._max_items = max(1, int(max_items))
        self._cache: OrderedDict[str, TextAnalysis | None] = OrderedDict()
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0

    @property
    def status(self) -> AnalyzerStatus:
        try:
            return AnalyzerStatus(self._inner.status)
        except Exception:
            return AnalyzerStatus.UNAVAILABLE

    @property
    def hits(self) -> int:
        with self._lock:
            return self._hits

    @property
    def misses(self) -> int:
        with self._lock:
            return self._misses

    def __len__(self) -> int:
        with self._lock:
            return len(self._cache)

    def analyze(self, text: str) -> TextAnalysis | None:
        try:
            key = _cache_key(text)
        except Exception:
            return None
        with self._lock:
            cached = self._cache.get(key, _MISS)
            if cached is not _MISS:
                self._cache.move_to_end(key)
                self._hits += 1
                return cached
            self._misses += 1
        try:
            result = self._inner.analyze(text)
        except Exception:
            return None
        if result is None and self.status is not AnalyzerStatus.DISABLED:
            return None
        with self._lock:
            self._cache[key] = result
            self._cache.move_to_end(key)
            while len(self._cache) > self._max_items:
                self._cache.popitem(last=False)
        return result


# --- financial-text gate ---------------------------------------------------------------------

_FINANCIAL_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"\b(?:earnings|eps|guidance|revenues?|stocks?|analysts?|dividends?|buybacks?|"
        r"upgrad(?:e|es|ed|ing)|downgrad(?:e|es|ed|ing)|"
        r"mergers?|acquisitions?|acquires?|acquired|takeovers?|buyouts?|ipo|"
        r"initial public offering|price target|market cap(?:italization)?|"
        r"quarterly (?:results|profit|loss)|net (?:income|profit)|"
        r"beats? (?:estimates|expectations|forecasts)|"
        r"misses? (?:estimates|expectations|forecasts)|"
        r"nasdaq|nyse|s&p 500|dow jones|"
        r"central banks?|federal reserve|fomc|ecb|bank of england|bank of japan|"
        r"rate (?:cut|cuts|hike|hikes|decision))\b",
        re.IGNORECASE,
    ),
    # "shares" is ambiguous ("shares intelligence"); skip obvious non-equity usages.
    re.compile(
        r"\bshares\b(?!\s+(?:intelligence|information|a|an|the|his|her|their|its|"
        r"border|footage|video|images|data)\b)",
        re.IGNORECASE,
    ),
    re.compile(r"\bshare price\b", re.IGNORECASE),
    # "the Fed" (case-sensitive so "fed up" / "well-fed" do not match).
    re.compile(r"\bFed\b"),
    # Cashtag tickers: $NVDA, $AAPL (1-5 capital letters); "$5 billion" does not match.
    re.compile(r"(?<![\w$])\$[A-Z]{1,5}\b"),
    # Exchange-qualified tickers: (NASDAQ: NVDA), NYSE:TSM
    re.compile(r"\b(?:NASDAQ|NYSE|LSE|TSX|AMEX)\s*:\s*[A-Z]{1,5}\b"),
)


def is_financial_text(text: str) -> bool:
    """Deterministic keyword gate: True for company / market-relevant financial text.

    Used so the financial sentiment model only runs on such text, never on geopolitical or
    disaster reporting. Conservative and explainable; no ML, no I/O.
    """
    if not isinstance(text, str) or not text.strip():
        return False
    return any(p.search(text) for p in _FINANCIAL_PATTERNS)


__all__ = [
    "AnalyzerStatus",
    "CachingAnalyzer",
    "FinancialTextAnalyzer",
    "NullAnalyzer",
    "TextAnalysis",
    "is_financial_text",
]
