from __future__ import annotations

import threading

import pytest

from app.world.text.analyzer import (
    AnalyzerStatus,
    CachingAnalyzer,
    FinancialTextAnalyzer,
    NullAnalyzer,
    TextAnalysis,
    is_financial_text,
)


def _ta(label: str = "positive") -> TextAnalysis:
    return TextAnalysis(label=label, scores={label: 0.9}, model="stub", latency_ms=1.0)  # type: ignore[arg-type]


class StubAnalyzer:
    def __init__(self, status: AnalyzerStatus = AnalyzerStatus.AVAILABLE, result=True) -> None:
        self.status = status
        self.result = result
        self.calls = 0
        self._lock = threading.Lock()

    def analyze(self, text: str) -> TextAnalysis | None:
        with self._lock:
            self.calls += 1
        return _ta() if self.result else None


class RaisingAnalyzer:
    status = AnalyzerStatus.AVAILABLE

    def analyze(self, text: str) -> TextAnalysis | None:
        raise RuntimeError("boom")


# --- Null -------------------------------------------------------------------------------------


def test_null_analyzer() -> None:
    n = NullAnalyzer()
    assert n.status is AnalyzerStatus.DISABLED
    assert n.analyze("NVIDIA beats earnings estimates") is None
    assert isinstance(n, FinancialTextAnalyzer)


def test_text_analysis_model() -> None:
    ta = TextAnalysis(label="neutral", scores={"neutral": 1.0}, model="m")
    assert ta.latency_ms is None
    with pytest.raises(ValueError):
        TextAnalysis(label="bullish", scores={}, model="m")  # type: ignore[arg-type]


# --- Caching ----------------------------------------------------------------------------------


def test_cache_hit_miss_counts_and_strip_key() -> None:
    inner = StubAnalyzer()
    c = CachingAnalyzer(inner)
    assert c.analyze("hello") is not None
    assert (c.hits, c.misses) == (0, 1)
    assert c.analyze("  hello \n") is not None  # same key after strip
    assert c.analyze("hello") is not None
    assert (c.hits, c.misses) == (2, 1)
    assert inner.calls == 1
    c.analyze("other")
    assert (c.hits, c.misses) == (2, 2)
    assert inner.calls == 2


def test_status_delegated() -> None:
    inner = StubAnalyzer(status=AnalyzerStatus.LOADING)
    c = CachingAnalyzer(inner)
    assert c.status is AnalyzerStatus.LOADING
    inner.status = AnalyzerStatus.AVAILABLE
    assert c.status is AnalyzerStatus.AVAILABLE
    assert isinstance(c, FinancialTextAnalyzer)


def test_lru_eviction_bound_and_recency() -> None:
    inner = StubAnalyzer()
    c = CachingAnalyzer(inner, max_items=3)
    for t in ("a", "b", "c"):
        c.analyze(t)
    c.analyze("a")  # refresh a -> b is now least recent
    c.analyze("d")  # evicts b
    assert len(c) == 3
    calls = inner.calls
    c.analyze("a")
    c.analyze("c")
    c.analyze("d")
    assert inner.calls == calls  # all still cached
    c.analyze("b")  # was evicted -> recomputed
    assert inner.calls == calls + 1
    for i in range(50):
        c.analyze(f"t{i}")
    assert len(c) == 3


def test_unavailable_none_not_cached_so_recovery_works() -> None:
    inner = StubAnalyzer(status=AnalyzerStatus.UNAVAILABLE, result=False)
    c = CachingAnalyzer(inner)
    assert c.analyze("x") is None
    assert c.analyze("x") is None
    assert inner.calls == 2
    assert len(c) == 0
    # recovery
    inner.status = AnalyzerStatus.AVAILABLE
    inner.result = True
    assert c.analyze("x") is not None
    assert c.analyze("x") is not None
    assert inner.calls == 3


def test_loading_none_not_cached() -> None:
    inner = StubAnalyzer(status=AnalyzerStatus.LOADING, result=False)
    c = CachingAnalyzer(inner)
    c.analyze("x")
    c.analyze("x")
    assert inner.calls == 2
    assert len(c) == 0


def test_disabled_none_is_cached() -> None:
    inner = StubAnalyzer(status=AnalyzerStatus.DISABLED, result=False)
    c = CachingAnalyzer(inner)
    assert c.analyze("x") is None
    assert c.analyze("x") is None
    assert inner.calls == 1
    assert (c.hits, c.misses) == (1, 1)


def test_wraps_null_analyzer() -> None:
    c = CachingAnalyzer(NullAnalyzer())
    assert c.status is AnalyzerStatus.DISABLED
    assert c.analyze("y") is None
    assert c.analyze("y") is None
    assert c.hits == 1


def test_exception_safety() -> None:
    c = CachingAnalyzer(RaisingAnalyzer())
    assert c.analyze("x") is None
    assert c.analyze("x") is None
    assert len(c) == 0
    assert c.misses == 2


def test_non_string_input_does_not_raise() -> None:
    c = CachingAnalyzer(StubAnalyzer())
    assert c.analyze(None) is None  # type: ignore[arg-type]


def test_thread_safety_smoke() -> None:
    inner = StubAnalyzer()
    c = CachingAnalyzer(inner, max_items=16)
    errors: list[BaseException] = []

    def work(seed: int) -> None:
        try:
            for i in range(300):
                assert c.analyze(f"text-{(i * 7 + seed) % 40}") is not None
        except BaseException as exc:  # pragma: no cover - failure path
            errors.append(exc)

    threads = [threading.Thread(target=work, args=(s,)) for s in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert len(c) <= 16
    assert c.hits + c.misses == 8 * 300


# --- Gate -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "NVIDIA beats earnings estimates",
        "Apple raises full-year revenue guidance",
        "Analyst upgrades Tesla to buy",
        "Morgan Stanley downgrades Intel on weak demand",
        "Microsoft to acquire game studio in $10 billion merger",
        "Startup files for IPO on Nasdaq",
        "$NVDA jumps after the bell",
        "Chipmaker (NASDAQ: AMD) unveils new accelerators",
        "Shares of TSMC rose 3% in Taipei",
        "Federal Reserve holds rates; central bank signals caution",
        "ECB weighs rate cut",
        "The Fed signals patience",
        "Company stock falls on guidance cut",
    ],
)
def test_gate_positives(text: str) -> None:
    assert is_financial_text(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "Iran seizes tanker in Strait of Hormuz amid rising tensions",
        "Magnitude 7.4 earthquake strikes off Taiwan coast",
        "Ceasefire talks stall as troops mass near border",
        "Major cloud region suffers multi-hour outage",
        "Government stockpile of grain released",  # 'stockpile' is not 'stock'
        "Minister shares intelligence with allies",
        "Farmers are fed up with drought",
        "Cost was $5 billion",
        "",
        "   ",
    ],
)
def test_gate_negatives(text: str) -> None:
    assert is_financial_text(text) is False


def test_gate_non_string() -> None:
    assert is_financial_text(None) is False  # type: ignore[arg-type]


def test_no_heavy_imports() -> None:
    import app.world.text.analyzer as mod

    with open(mod.__file__, encoding="utf-8") as fh:
        src = fh.read()
    assert "import torch" not in src and "import transformers" not in src
