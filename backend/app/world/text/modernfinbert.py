"""ModernFinBERT financial-text sentiment analyzer (optional, CPU-only, lazily loaded).

Model: ``tabularisai/ModernFinBERT`` -- ModernBERT-base fine-tuned for financial sentiment
(bearish / neutral / bullish), 149.6M parameters, Apache-2.0. See ``docs/models.md``.

Scope: a sentiment FEATURE for company / market / financial headlines only. It is not a
geopolitical reasoner, severity scorer, corroboration signal or trading signal. Callers decide
whether text is financial (``analyzer.is_financial_text``); this module does not gate.

Guarantees
- Importing this module imports neither ``torch`` nor ``transformers`` (nor ``huggingface_hub``).
- Constructing :class:`ModernFinBERTAnalyzer` does nothing: no I/O, no network, no imports of the
  heavy libraries. The model is loaded on the first ``analyze`` / ``analyze_many`` call, at most
  once, under a lock. Status: LOADING while loading, then AVAILABLE or UNAVAILABLE.
- Any load failure (deps missing, no cache and no network, corrupt files, unexpected labels)
  becomes UNAVAILABLE and ``analyze`` returns ``None``. Nothing here raises to the caller.
- The default loader uses ``local_files_only=True``: it never touches the network unless
  downloading is explicitly enabled (``allow_download=True`` or the env var
  ``ECHO_WORLD_TEXT_ALLOW_DOWNLOAD=1``) or an operator runs the prefetch helper
  ``python -m app.world.text.modernfinbert``.
- A concurrent caller that arrives while another thread is loading gets ``None`` immediately (it
  does not block the event loop); the next call after loading finishes gets a result.
- Weights are pinned to :data:`REVISION` (a commit hash). ``trust_remote_code`` is never enabled.
"""

from __future__ import annotations

import importlib.util
import logging
import os
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Protocol

from app.world.text.analyzer import AnalyzerStatus, TextAnalysis

logger = logging.getLogger("echo.world.text")

MODEL_ID = "tabularisai/ModernFinBERT"
# Commit of tabularisai/ModernFinBERT (lastModified 2025-11-25) that docs/models.md was measured on.
REVISION = "6c6de8332ea7f6824c0f8917358dce1e669c1710"
LICENSE = "apache-2.0"

DEFAULT_MAX_LENGTH = 256  # tokens; headlines are ~10-40 tokens, model context is 8192
DEFAULT_BATCH_SIZE = 16
_MIN_MAX_LENGTH = 8
_MAX_MAX_LENGTH = 8192
_CHARS_PER_TOKEN_CAP = 8  # hard character pre-cap before tokenisation (bounds tokenizer work)

CANONICAL_LABELS: tuple[str, ...] = ("positive", "negative", "neutral")
_LABEL_MAP: dict[str, str] = {
    "bullish": "positive",
    "positive": "positive",
    "pos": "positive",
    "bearish": "negative",
    "negative": "negative",
    "neg": "negative",
    "neutral": "neutral",
    "neu": "neutral",
}


def map_label(raw: object) -> str | None:
    """Map a model-native label (bullish/bearish/neutral, positive/negative) to the canonical set.

    Returns ``None`` for anything unrecognised (e.g. ``LABEL_0``) -- never guesses.
    """
    if not isinstance(raw, str):
        return None
    return _LABEL_MAP.get(raw.strip().lower())


class LoadedModel(Protocol):
    """What a loader returns: label metadata plus a batched probability function."""

    id2label: Mapping[int, str]

    def predict_proba(self, texts: Sequence[str], max_length: int) -> Sequence[Sequence[float]]:
        """Probabilities per text, columns in ``id2label`` index order. Truncates to max_length."""
        ...


Loader = Callable[[], LoadedModel]


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def deps_available() -> bool:
    """True when ``torch`` and ``transformers`` are importable (checked without importing)."""
    return _module_available("torch") and _module_available("transformers")


def is_model_cached(model_id: str = MODEL_ID, revision: str = REVISION) -> bool:
    """True when the pinned revision's weights are already in the local Hugging Face cache."""
    if not _module_available("huggingface_hub"):
        return False
    try:
        from huggingface_hub import try_to_load_from_cache

        for filename in ("config.json", "model.safetensors"):
            path = try_to_load_from_cache(model_id, filename, revision=revision)
            if not isinstance(path, str):
                return False
        return True
    except Exception:
        return False


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


class _TransformersModel:
    """Real backend. Only constructed inside the loader, so heavy imports stay lazy."""

    def __init__(self, tokenizer: Any, model: Any, torch: Any) -> None:
        self._tokenizer = tokenizer
        self._model = model
        self._torch = torch
        self.id2label: Mapping[int, str] = {
            int(k): str(v) for k, v in model.config.id2label.items()
        }

    def predict_proba(self, texts: Sequence[str], max_length: int) -> Sequence[Sequence[float]]:
        enc = self._tokenizer(
            list(texts),
            padding=True,
            truncation=True,
            max_length=max_length,
            return_tensors="pt",
        )
        with self._torch.inference_mode():
            logits = self._model(**enc).logits
        return self._torch.softmax(logits.float(), dim=-1).tolist()


def load_transformers_model(
    model_id: str = MODEL_ID, revision: str = REVISION, *, allow_download: bool = False
) -> LoadedModel:
    """Import torch/transformers and load the pinned model on CPU. Raises on any failure."""
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    local_only = not allow_download
    kwargs: dict[str, Any] = {
        "revision": revision,
        "local_files_only": local_only,
        "trust_remote_code": False,
    }
    tokenizer = AutoTokenizer.from_pretrained(model_id, **kwargs)
    model = AutoModelForSequenceClassification.from_pretrained(
        model_id, use_safetensors=True, **kwargs
    )
    model.to("cpu")
    model.eval()
    return _TransformersModel(tokenizer, model, torch)


class ModernFinBERTAnalyzer:
    """Lazy, thread-safe, never-raising financial sentiment analyzer (see module docstring).

    ``loader`` is injectable for tests and must return a :class:`LoadedModel`. The default loader
    reads the pinned revision from the local HF cache only (see ``allow_download``).
    """

    model_id = MODEL_ID
    revision = REVISION

    def __init__(
        self,
        *,
        loader: Loader | None = None,
        max_length: int = DEFAULT_MAX_LENGTH,
        batch_size: int = DEFAULT_BATCH_SIZE,
        allow_download: bool | None = None,
    ) -> None:
        self._allow_download = (
            _env_flag("ECHO_WORLD_TEXT_ALLOW_DOWNLOAD")
            if allow_download is None
            else allow_download
        )
        self._loader = loader
        self.max_length = min(max(int(max_length), _MIN_MAX_LENGTH), _MAX_MAX_LENGTH)
        self.batch_size = max(1, int(batch_size))
        self._state_lock = threading.Lock()  # guards _status/_model/_loading
        self._load_lock = threading.Lock()  # held by the one thread that is loading
        self._status = AnalyzerStatus.LOADING  # "not ready yet": the model loads on first use
        self._loaded = False  # a load attempt has finished (success or failure)
        self._loading = False
        self._model: LoadedModel | None = None
        self._index_to_label: dict[int, str] = {}
        self.load_error: str | None = None
        self.load_seconds: float | None = None
        if loader is None and not deps_available():
            # find_spec only: nothing is imported. Known-unavailable up front, no load attempt.
            self._set_unavailable("torch/transformers not installed (uv sync --group text)")

    # -- status ---------------------------------------------------------------------------------

    @property
    def status(self) -> AnalyzerStatus:
        """UNAVAILABLE (deps missing / load failed), AVAILABLE (loaded), else LOADING.

        LOADING covers both "load in progress" and "not loaded yet, will load on first use": we
        cannot honestly report AVAILABLE before the weights have actually been read.
        """
        with self._state_lock:
            return self._status

    @property
    def is_loaded(self) -> bool:
        with self._state_lock:
            return self._model is not None

    # -- loading --------------------------------------------------------------------------------

    def _default_loader(self) -> LoadedModel:
        return load_transformers_model(MODEL_ID, REVISION, allow_download=self._allow_download)

    def _set_unavailable(self, reason: str) -> None:
        with self._state_lock:
            self._status = AnalyzerStatus.UNAVAILABLE
            self._model = None
            self._loaded = True
            self._loading = False
            self.load_error = reason
        logger.warning("modernfinbert_unavailable", extra={"reason": reason})

    def _ensure_loaded(self) -> LoadedModel | None:
        """Return the loaded model, loading it once. ``None`` if unavailable or another thread
        is currently loading. No raise."""
        with self._state_lock:
            if self._loaded:
                return self._model
            if self._loading:
                return None
        if not self._load_lock.acquire(blocking=False):
            return None  # another thread won the race and is loading
        try:
            with self._state_lock:
                if self._loaded:
                    return self._model
                self._loading = True
                self._status = AnalyzerStatus.LOADING
            started = time.perf_counter()
            try:
                model = (self._loader or self._default_loader)()
                index_to_label = self._validate_labels(model)
            except Exception as exc:
                self._set_unavailable(f"{type(exc).__name__}: {str(exc)[:300]}")
                return None
            with self._state_lock:
                self._model = model
                self._index_to_label = index_to_label
                self._status = AnalyzerStatus.AVAILABLE
                self._loaded = True
                self._loading = False
                self.load_seconds = time.perf_counter() - started
            logger.info(
                "modernfinbert_loaded",
                extra={"model": MODEL_ID, "revision": REVISION[:12], "seconds": self.load_seconds},
            )
            return model
        finally:
            self._load_lock.release()

    @staticmethod
    def _validate_labels(model: LoadedModel) -> dict[int, str]:
        mapping: dict[int, str] = {}
        for idx, raw in dict(model.id2label).items():
            canon = map_label(raw)
            if canon is None:
                raise ValueError(f"unrecognised model label {raw!r}")
            mapping[int(idx)] = canon
        if set(mapping.values()) != set(CANONICAL_LABELS) or len(mapping) != len(CANONICAL_LABELS):
            raise ValueError(f"model labels do not map onto {CANONICAL_LABELS}: {mapping}")
        return mapping

    # -- inference ------------------------------------------------------------------------------

    def _prepare(self, text: object) -> str | None:
        if not isinstance(text, str):
            return None
        cleaned = text.strip()
        if not cleaned:
            return None
        return cleaned[: self.max_length * _CHARS_PER_TOKEN_CAP]

    def _to_analysis(self, probs: Sequence[float], latency_ms: float) -> TextAnalysis | None:
        scores = dict.fromkeys(CANONICAL_LABELS, 0.0)
        for idx, p in enumerate(probs):
            label = self._index_to_label.get(idx)
            if label is None:
                return None
            value = float(p)
            if value != value:  # NaN guard (min/max would silently turn NaN into 0)
                return None
            scores[label] = min(1.0, max(0.0, value))
        # ties resolve in CANONICAL_LABELS order (positive, negative, neutral): deterministic
        label = max(CANONICAL_LABELS, key=lambda name: scores[name])
        return TextAnalysis(
            label=label,  # type: ignore[arg-type]
            scores=scores,
            model=f"{MODEL_ID}@{REVISION[:12]}",
            latency_ms=latency_ms,
        )

    def analyze(self, text: str) -> TextAnalysis | None:
        """Sentiment of one financial text, or ``None`` (unavailable/empty/loading). No raise."""
        try:
            results = self.analyze_many([text])
        except Exception:
            return None
        return results[0] if results else None

    def analyze_many(self, texts: Sequence[str]) -> list[TextAnalysis | None]:
        """Batch analysis. Result list is aligned with ``texts``; failed/empty items are ``None``.

        Texts are processed in batches of ``batch_size`` (sorted by length so padding stays
        small), truncated to ``max_length`` tokens. Never raises.
        """
        try:
            items = list(texts)
        except Exception:
            return []
        results: list[TextAnalysis | None] = [None] * len(items)
        prepared = [(i, self._prepare(t)) for i, t in enumerate(items)]
        todo = [(i, t) for i, t in prepared if t is not None]
        if not todo:
            return results
        model = self._ensure_loaded()
        if model is None:
            return results
        todo.sort(key=lambda pair: len(pair[1]))
        for start in range(0, len(todo), self.batch_size):
            chunk = todo[start : start + self.batch_size]
            t0 = time.perf_counter()
            try:
                probs = model.predict_proba([t for _, t in chunk], self.max_length)
                if len(probs) != len(chunk):
                    raise ValueError("predict_proba returned wrong batch size")
            except Exception as exc:
                logger.warning(
                    "modernfinbert_inference_failed",
                    extra={"error": f"{type(exc).__name__}: {str(exc)[:200]}"},
                )
                continue
            per_item_ms = (time.perf_counter() - t0) * 1000.0 / len(chunk)
            for (idx, _), row in zip(chunk, probs, strict=True):
                try:
                    results[idx] = self._to_analysis(row, per_item_ms)
                except Exception:
                    results[idx] = None
        return results


def prefetch(allow_download: bool = True) -> int:
    """Operator helper: download/verify the pinned revision into the HF cache. Returns exit code."""
    if not deps_available():
        print("torch/transformers missing: run `uv sync --group text` first")
        return 2
    try:
        load_transformers_model(MODEL_ID, REVISION, allow_download=allow_download)
    except Exception as exc:
        print(f"prefetch failed: {type(exc).__name__}: {exc}")
        return 1
    print(f"ok: {MODEL_ID}@{REVISION} cached")
    return 0


__all__ = [
    "CANONICAL_LABELS",
    "DEFAULT_BATCH_SIZE",
    "DEFAULT_MAX_LENGTH",
    "LICENSE",
    "MODEL_ID",
    "REVISION",
    "LoadedModel",
    "ModernFinBERTAnalyzer",
    "deps_available",
    "is_model_cached",
    "load_transformers_model",
    "map_label",
    "prefetch",
]


if __name__ == "__main__":
    raise SystemExit(prefetch())
