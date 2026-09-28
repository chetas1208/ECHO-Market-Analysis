# Models

ECHO Day 3 ships exactly one optional ML model. Everything else in the world pipeline (taxonomy, entities,
geo, severity, channels, corroboration, dedup) is deterministic and needs no model.

## ModernFinBERT (financial text sentiment)

| Item | Value |
|---|---|
| Hugging Face id | `tabularisai/ModernFinBERT` (constant `MODEL_ID` in `backend/app/world/text/modernfinbert.py`) |
| Pinned revision | `6c6de8332ea7f6824c0f8917358dce1e669c1710` (constant `REVISION`; repo last modified 2025-11-25) |
| Architecture | `ModernBertForSequenceClassification`, fine-tuned from `answerdotai/ModernBERT-base`, 22 layers, hidden 768 |
| Parameters | 149,607,171 (F32) |
| Labels (native) | `bearish` / `neutral` / `bullish`, mapped to `negative` / `neutral` / `positive` |
| License | Apache-2.0 (model card + repo metadata) |
| Training data (per model card) | synthetic + real financial data: news, tweets, crypto, macro. Not independently verified by us. |
| Runtime | CPU only, `torch.inference_mode`, `max_length=256` tokens (model context 8192), batch size 16 |

Why this checkpoint: it is the model named "ModernFinBERT", ModernBERT-base backbone, permissive license, safetensors,
and small enough for CPU. An alternative, `beethogedeon/Modern-FinBERT` (ModernBERT-base, Financial PhraseBank
fine-tune, apache-2.0), exists but has far fewer downloads and a narrower training set. We did not benchmark either on
our own data; the model card's benchmark numbers (avg accuracy 0.75, F1 0.63 over FIQA/Twitter/JeanBaptiste) are the
vendor's own and are NOT re-verified here.

### Measured (this machine, not a guarantee)

Measured 2026-09-20 in a separate venv (`/tmp/echo-textenv`, CPython 3.12, `torch 2.14.0+cpu`, `transformers 5.17.0`),
Linux x86_64, 20 logical cores shared with ~25 other agent processes (torch used 10 threads), page cache warm.
50 short financial headlines (10 distinct, repeated), `HF_HUB_OFFLINE=1`.

| Metric | Result |
|---|---|
| Disk (HF snapshot: `model.safetensors` 598,442,860 B + tokenizer/config) | 575 MB (`du -shL` of the model cache dir) |
| Cold load (`from_pretrained` on CPU, files already on local disk) | 2.1 s; `import torch, transformers` adds ~2.5 s more, once |
| First download over network | ~20 s wall on this machine (one-off, `prefetch`); network-dependent |
| Warm inference, single headline (`analyze`), n=50 | p50 35.5 ms, p95 37.8 ms |
| Warm inference, batched (`analyze_many`, batch 16), 50 headlines | 440 ms total, about 8.8 ms per headline |
| Process RSS | 12 MB bare Python, 245 MB after importing torch+transformers, 835 MB after model load, 856 MB after 100 inferences. Model delta over imports: about 610 MB. Peak RSS 853 MB. |
| Torch CPU wheel install | env total 954 MB (torch CPU + transformers + deps) |

Caveats: cold load excludes a truly cold disk cache (the weights were just downloaded, so they were in the OS page
cache). Latencies are wall-clock on a busy shared box; expect the same order of magnitude, not the same digits.
On a default `uv sync --group text` on Linux, PyPI resolves the CUDA build of torch (several GB of `nvidia-*` wheels).
For a CPU-only install use the PyTorch CPU index, e.g.
`uv pip install --index-url https://download.pytorch.org/whl/cpu torch` in a dedicated environment (we did not add
a `[tool.uv.sources]` index override because only the `text` dependency group is owned by this change).

Sanity outputs on unseen headlines (not a benchmark, 10 hand-written examples): all 10 matched intuitive labels
(e.g. "Apple reports record quarterly revenue, beating analyst estimates" -> positive 0.98;
"NVIDIA shares plunge after guidance disappoints and analysts downgrade the stock" -> negative 0.996;
"The Federal Reserve left interest rates unchanged..." -> neutral 0.98). Scores are softmax outputs of a
classifier, not probabilities of any market outcome.

### Exact role

- A financial / company / market text sentiment FEATURE: label (positive/negative/neutral) plus three softmax scores
  attached to an event when its text is financial (company, earnings, analyst, deal, central-bank/market
  headlines; gate: `is_financial_text` in `text/analyzer.py`).
- It is optional and additive: an event is fully normalized, scored and persisted with the analyzer OFF, UNAVAILABLE
  or returning `None`.

### What it is NOT used for

- Geopolitical reasoning (wars, sanctions, chokepoints, disasters): the model was trained on financial text and
  its sentiment on such text is meaningless for this purpose.
- Severity, novelty, corroboration or confidence scores: those are deterministic heuristics and do not read the
  sentiment.
- Economic channels (directional pressure): derived from rules over class/entities/geo, not from sentiment.
- Trading decisions, price/move predictions or recommendations of any kind. Sentiment is descriptive only.
- Any claim of accuracy on ECHO data: it has not been evaluated on our events.

### Behaviour guarantees (implementation)

- Importing `app.world.text.modernfinbert` imports neither `torch`, `transformers` nor `huggingface_hub`
  (tested in a subprocess).
- Constructing the analyzer does nothing. The model loads lazily on first `analyze`/`analyze_many`, once, under a
  lock. Status: `LOADING` (not yet loaded / loading) -> `AVAILABLE`, or `UNAVAILABLE` on any failure.
  Missing packages report `UNAVAILABLE` immediately, without a load attempt.
- `analyze` / `analyze_many` never raise: failures return `None` (per item for `analyze_many`).
  A concurrent caller arriving while another thread loads gets `None` immediately instead of blocking.
- No network at app startup and none at inference: the default loader uses `local_files_only=True` against the
  pinned revision. Downloading happens only when an operator runs the prefetch command below (or explicitly sets
  `ECHO_WORLD_TEXT_ALLOW_DOWNLOAD=1`). `trust_remote_code` is never enabled; weights load from safetensors only.
- Truncation: text is character-capped (`max_length * 8`) before tokenization and token-truncated to `max_length`.
- A failed load is not retried within the process (restart, or construct a new analyzer, to retry).

### Enable

```bash
cd backend
uv sync --group text                       # torch + transformers (see CPU-wheel note above)
uv run python -m app.world.text.modernfinbert   # one-off prefetch/verify of the pinned revision (needs network)
# .env
ECHO_WORLD_TEXT_MODEL=modernfinbert        # default: off
```

The world status endpoint reports the analyzer as `AVAILABLE|LOADING|UNAVAILABLE|DISABLED`. With
`ECHO_WORLD_TEXT_MODEL=off` (default) the analyzer is `DISABLED` and nothing is imported or loaded.

### Cache location and weights

- Weights live in the standard Hugging Face cache: `~/.cache/huggingface/hub/models--tabularisai--ModernFinBERT/`
  (override with `HF_HOME` / `HF_HUB_CACHE`). Docker: mount a volume there so containers do not re-download.
- No weights are committed to this repository, and none are baked into git-tracked files. Delete the cache directory
  to remove the model.
- Upgrading: change `REVISION` in `modernfinbert.py` deliberately, re-run the prefetch command and the tests, and
  update this document (revision, disk, RSS, latency).

### Tests

`backend/tests/world/test_modernfinbert.py`: 36 tests need no model, torch or network (lazy construction, status
transitions with an injected `loader`, failure paths, label mapping, batching, truncation, concurrency). One test
runs the real model and is skipped unless `torch`, `transformers` and the cached pinned revision are all present.

## Day 6 Forecasting stack

The forecasting implementation is in `backend/app/forecasting/` and is intentionally
optional-dependency aware.

| Component | Role | Current clean-runtime status |
|---|---|---|
| Chronos-2-Small (`amazon/chronos-2`) | market-only baseline | `BASELINE_UNAVAILABLE` when the package/checkpoint is absent; local-only loading, no silent fallback label |
| LightGBM quantile regressors | event-conditioned q10/q50/q90 models | optional backend; fixed conservative parameters |
| Linear pinball model | deterministic local fallback | `linear_pinball_fallback`, explicitly recorded in artifacts |
| HAR-RV | volatility context, not event alpha | pure NumPy implementation, no heavy refit per request |

The default environment has no cached Chronos checkpoint and no LightGBM package,
so no fabricated Chronos or LightGBM measurements are claimed. The training report
records backend status and actual metrics for the supplied dataset.
