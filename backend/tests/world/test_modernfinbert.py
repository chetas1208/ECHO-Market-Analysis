"""ModernFinBERTAnalyzer tests. All but the last need NO model, torch or network."""

from __future__ import annotations

import subprocess
import sys
import threading
import time
from collections.abc import Sequence

import pytest

from app.world.text import modernfinbert as mfb
from app.world.text.analyzer import AnalyzerStatus, FinancialTextAnalyzer, TextAnalysis
from app.world.text.modernfinbert import (
    MODEL_ID,
    REVISION,
    ModernFinBERTAnalyzer,
    map_label,
)


class FakeModel:
    """Deterministic stand-in: 'up' -> bullish, 'down' -> bearish, else neutral."""

    def __init__(self, id2label: dict[int, str] | None = None) -> None:
        self.id2label = id2label or {0: "bearish", 1: "neutral", 2: "bullish"}
        self.calls: list[tuple[list[str], int]] = []

    def predict_proba(self, texts: Sequence[str], max_length: int) -> list[list[float]]:
        self.calls.append((list(texts), max_length))
        name_to_idx = {v: k for k, v in self.id2label.items()}
        rows = []
        for t in texts:
            row = [0.05] * len(self.id2label)
            if "up" in t:
                row[name_to_idx.get("bullish", name_to_idx.get("positive", 0))] = 0.9
            elif "down" in t:
                row[name_to_idx.get("bearish", name_to_idx.get("negative", 0))] = 0.9
            else:
                row[name_to_idx["neutral"]] = 0.9
            rows.append(row)
        return rows


def make(fake: FakeModel | None = None, **kwargs) -> tuple[ModernFinBERTAnalyzer, FakeModel]:
    model = fake or FakeModel()
    return ModernFinBERTAnalyzer(loader=lambda: model, **kwargs), model


# --- import / construction are cheap and dependency-free ------------------------------------------


def test_module_import_does_not_import_torch_or_transformers():
    code = (
        "import sys; import app.world.text.modernfinbert; "
        "bad = [m for m in ('torch','transformers','huggingface_hub') if m in sys.modules]; "
        "print(','.join(bad)); sys.exit(1 if bad else 0)"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=False, timeout=60
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_pinned_constants():
    assert MODEL_ID == "tabularisai/ModernFinBERT"
    assert len(REVISION) == 40 and all(c in "0123456789abcdef" for c in REVISION)


def test_satisfies_protocol():
    a, _ = make()
    assert isinstance(a, FinancialTextAnalyzer)


def test_constructing_does_not_load():
    calls = []

    def loader():
        calls.append(1)
        return FakeModel()

    a = ModernFinBERTAnalyzer(loader=loader)
    assert calls == []
    assert a.status is AnalyzerStatus.LOADING
    assert a.is_loaded is False


# --- unavailable without deps / on any failure ------------------------------------------


def test_unavailable_without_deps_and_never_raises(monkeypatch):
    monkeypatch.setattr(mfb, "deps_available", lambda: False)
    a = ModernFinBERTAnalyzer()  # default loader, deps "missing"
    assert a.status is AnalyzerStatus.UNAVAILABLE
    assert a.load_error and "uv sync --group text" in a.load_error
    assert a.analyze("Apple stock up") is None
    assert a.analyze_many(["a", "b"]) == [None, None]
    assert a.status is AnalyzerStatus.UNAVAILABLE


@pytest.mark.parametrize(
    "exc", [ImportError("no torch"), OSError("offline, no cache"), MemoryError()]
)
def test_loader_failure_is_unavailable_and_not_retried(exc):
    calls = []

    def loader():
        calls.append(1)
        raise exc

    a = ModernFinBERTAnalyzer(loader=loader)
    assert a.analyze("Shares up") is None
    assert a.status is AnalyzerStatus.UNAVAILABLE
    assert a.load_error
    assert a.analyze("Shares up again") is None
    assert calls == [1]


def test_default_loader_is_offline_by_default(monkeypatch):
    seen = {}

    def fake_load(model_id, revision, *, allow_download=False):
        seen.update(model_id=model_id, revision=revision, allow_download=allow_download)
        raise OSError("not cached")

    monkeypatch.setattr(mfb, "deps_available", lambda: True)
    monkeypatch.setattr(mfb, "load_transformers_model", fake_load)
    monkeypatch.delenv("ECHO_WORLD_TEXT_ALLOW_DOWNLOAD", raising=False)
    a = ModernFinBERTAnalyzer()
    assert seen == {}  # nothing on construction
    assert a.analyze("x up") is None
    assert seen == {"model_id": MODEL_ID, "revision": REVISION, "allow_download": False}
    assert a.status is AnalyzerStatus.UNAVAILABLE


def test_allow_download_via_env(monkeypatch):
    monkeypatch.setenv("ECHO_WORLD_TEXT_ALLOW_DOWNLOAD", "1")
    assert ModernFinBERTAnalyzer(loader=lambda: FakeModel())._allow_download is True
    assert (
        ModernFinBERTAnalyzer(loader=lambda: FakeModel(), allow_download=False)._allow_download
        is False
    )


def test_unrecognised_labels_make_it_unavailable():
    a, _ = make(FakeModel({0: "LABEL_0", 1: "LABEL_1", 2: "LABEL_2"}))
    assert a.analyze("Shares up") is None
    assert a.status is AnalyzerStatus.UNAVAILABLE
    assert "unrecognised" in (a.load_error or "")


def test_incomplete_label_set_is_unavailable():
    a, _ = make(FakeModel({0: "bearish", 1: "bullish"}))
    assert a.analyze("Shares up") is None
    assert a.status is AnalyzerStatus.UNAVAILABLE


def test_inference_error_returns_none_and_stays_available():
    class Boom(FakeModel):
        def predict_proba(self, texts, max_length):
            raise RuntimeError("oom")

    a, _ = make(Boom())
    assert a.analyze("Shares up") is None
    assert a.status is AnalyzerStatus.AVAILABLE


def test_bad_probability_rows_are_none():
    class NaNModel(FakeModel):
        def predict_proba(self, texts, max_length):
            return [[float("nan"), 0.5, 0.5] for _ in texts]

    a, _ = make(NaNModel())
    assert a.analyze("Shares up") is None


# --- status transitions ---------------------------------------------------------------------------


def test_status_loading_then_available_with_fake_loader():
    observed: list[AnalyzerStatus] = []
    holder: dict[str, ModernFinBERTAnalyzer] = {}

    def loader():
        observed.append(holder["a"].status)  # status seen from inside the load
        return FakeModel()

    a = ModernFinBERTAnalyzer(loader=loader)
    holder["a"] = a
    assert a.status is AnalyzerStatus.LOADING
    result = a.analyze("Profit up")
    assert observed == [AnalyzerStatus.LOADING]
    assert a.status is AnalyzerStatus.AVAILABLE
    assert a.is_loaded and a.load_seconds is not None
    assert isinstance(result, TextAnalysis)


def test_loads_once_across_calls():
    calls = []

    def loader():
        calls.append(1)
        return FakeModel()

    a = ModernFinBERTAnalyzer(loader=loader)
    for _ in range(5):
        a.analyze("Profit up")
    a.analyze_many(["a", "b"])
    assert calls == [1]


def test_concurrent_callers_load_once_and_waiters_get_none_not_blocked():
    started = threading.Event()
    release = threading.Event()
    calls = []

    def loader():
        calls.append(1)
        started.set()
        assert release.wait(5)
        return FakeModel()

    a = ModernFinBERTAnalyzer(loader=loader)
    first: list[TextAnalysis | None] = []
    t = threading.Thread(target=lambda: first.append(a.analyze("Profit up")))
    t.start()
    assert started.wait(5)
    assert a.status is AnalyzerStatus.LOADING
    t0 = time.perf_counter()
    assert a.analyze("Profit up") is None  # does not block while the other thread loads
    assert time.perf_counter() - t0 < 1.0
    release.set()
    t.join(5)
    assert first and first[0] is not None and first[0].label == "positive"
    assert a.analyze("Profit up") is not None
    assert calls == [1]
    assert a.status is AnalyzerStatus.AVAILABLE


def test_many_threads_single_load():
    calls = []
    lock = threading.Lock()

    def loader():
        with lock:
            calls.append(1)
        time.sleep(0.05)
        return FakeModel()

    a = ModernFinBERTAnalyzer(loader=loader)
    threads = [threading.Thread(target=lambda: a.analyze("Profit up")) for _ in range(12)]
    for th in threads:
        th.start()
    for th in threads:
        th.join(5)
    assert calls == [1]
    assert a.status is AnalyzerStatus.AVAILABLE


# --- label mapping --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "canon"),
    [
        ("bullish", "positive"),
        ("Bearish", "negative"),
        (" NEUTRAL ", "neutral"),
        ("positive", "positive"),
        ("negative", "negative"),
        ("LABEL_1", None),
        ("", None),
        (None, None),
        (3, None),
    ],
)
def test_map_label(raw, canon):
    assert map_label(raw) == canon


def test_analysis_labels_scores_and_model_tag():
    a, _ = make()
    up = a.analyze("Earnings up strongly")
    down = a.analyze("Shares down sharply")
    flat = a.analyze("Company files report")
    assert (up.label, down.label, flat.label) == ("positive", "negative", "neutral")
    for r in (up, down, flat):
        assert set(r.scores) == {"positive", "negative", "neutral"}
        assert all(0.0 <= v <= 1.0 for v in r.scores.values())
        assert sum(r.scores.values()) == pytest.approx(1.0, abs=1e-6)
        assert r.model == f"{MODEL_ID}@{REVISION[:12]}"
        assert r.latency_ms is not None and r.latency_ms >= 0.0
    assert up.scores["positive"] == pytest.approx(0.9)


def test_label_order_of_model_is_respected():
    # reversed label order: index 0 = bullish
    a, _ = make(FakeModel({0: "bullish", 1: "neutral", 2: "bearish"}))
    assert a.analyze("Shares up").label == "positive"
    assert a.analyze("Shares down").label == "negative"


# --- batching -------------------------------------------------------------------------------------


def test_analyze_many_batches_and_preserves_order():
    a, model = make(batch_size=4)
    texts = [
        f"item {i} " + ("up" if i % 3 == 0 else "down" if i % 3 == 1 else "") for i in range(10)
    ]
    out = a.analyze_many(texts)
    assert [len(c[0]) for c in model.calls] == [4, 4, 2]
    assert len(out) == 10
    expected = [
        "positive" if i % 3 == 0 else "negative" if i % 3 == 1 else "neutral" for i in range(10)
    ]
    assert [r.label for r in out] == expected


def test_analyze_many_empty_and_invalid_items_are_none_and_skipped():
    a, model = make()
    out = a.analyze_many(["Profit up", "", "   ", None, 5, "Shares down"])  # type: ignore[list-item]
    assert [r.label if r else None for r in out] == [
        "positive",
        None,
        None,
        None,
        None,
        "negative",
    ]
    assert sum(len(c[0]) for c in model.calls) == 2
    assert a.analyze_many([]) == []
    assert a.analyze("") is None


def test_analyze_many_all_empty_does_not_load():
    calls = []
    a = ModernFinBERTAnalyzer(loader=lambda: calls.append(1) or FakeModel())
    assert a.analyze_many(["", "  "]) == [None, None]
    assert calls == []
    assert a.status is AnalyzerStatus.LOADING


def test_failed_batch_only_nones_that_batch():
    class Flaky(FakeModel):
        def predict_proba(self, texts, max_length):
            if any("BAD" in t for t in texts):
                raise RuntimeError("boom")
            return super().predict_proba(texts, max_length)

    a, _ = make(Flaky(), batch_size=2)
    # sorted by length: the two short ones batch together, BAD-containing long ones together
    out = a.analyze_many(["up", "down", "BAD up up up up", "BAD down down down down"])
    assert [r is not None for r in out] == [True, True, False, False]


# --- truncation -----------------------------------------------------------------------------------


def test_max_length_passed_to_model_and_clamped():
    a, model = make(max_length=64)
    a.analyze("Profit up")
    assert model.calls[-1][1] == 64
    assert ModernFinBERTAnalyzer(loader=lambda: FakeModel(), max_length=1).max_length == 8
    assert ModernFinBERTAnalyzer(loader=lambda: FakeModel(), max_length=10**9).max_length == 8192


def test_overlong_text_is_character_capped_before_model():
    a, model = make(max_length=32)
    a.analyze("up " * 100_000)
    sent = model.calls[-1][0][0]
    assert len(sent) <= 32 * 8
    assert sent.startswith("up up")


def test_text_is_stripped():
    a, model = make()
    a.analyze("   Profit up \n")
    assert model.calls[-1][0] == ["Profit up"]


# --- optional real model --------------------------------------------------------------------------

_REAL_OK = mfb.deps_available() and mfb.is_model_cached()


@pytest.mark.skipif(not _REAL_OK, reason="torch/transformers or cached ModernFinBERT not available")
def test_real_model_labels_and_score_ranges(monkeypatch):
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    a = ModernFinBERTAnalyzer()
    positive = a.analyze("Apple reports record quarterly revenue, beating analyst estimates")
    negative = a.analyze("NVIDIA shares plunge after guidance disappoints and analysts downgrade")
    neutral = a.analyze("The board will hold its annual shareholder meeting in May")
    assert a.status is AnalyzerStatus.AVAILABLE
    assert positive and negative and neutral
    assert positive.label == "positive"
    assert negative.label == "negative"
    assert neutral.label == "neutral"
    for r in (positive, negative, neutral):
        assert set(r.scores) == {"positive", "negative", "neutral"}
        assert all(0.0 <= v <= 1.0 for v in r.scores.values())
        assert sum(r.scores.values()) == pytest.approx(1.0, abs=1e-3)
        assert r.scores[r.label] == max(r.scores.values())
    batch = a.analyze_many(["Profit up", "", "Stock crashes"])
    assert batch[1] is None and batch[0] is not None and batch[2] is not None
