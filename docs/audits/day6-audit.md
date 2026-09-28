# Day 6 audit — Forecasting Engine

Date: 2026-09-20  
Scope: event-conditioned CAR forecasting preview, reproducible training/evaluation,
calibration, OOD handling, optional model adapters, API, and Forecasts UI.

## Delivered

- Added the `backend/app/forecasting/` package with CAR target construction,
  cutoff-bound features, event-group chronological splits, train-only scaling,
  quantile models, conformal/isotonic calibration, HAR-RV volatility context,
  OOD checks, abstention, horizon recommendation, and immutable feature hashes.
- Added optional local-only Chronos-2-Small market baseline and optional LightGBM
  quantile backend. Missing dependencies/checkpoints remain explicit unavailable
  states; they are not relabeled as successful forecasts.
- Added reproducible fixture/train/evaluate CLIs and frozen artifact loading.
- Added `GET /api/v1/forecasting/status` and ephemeral
  `POST /api/v1/forecasts/preview`. Preview requests do not write
  `forecast_runs` or `forecast_points`; permanent forecast vintages remain Day 7.
- Replaced the Forecasts placeholder with a backend-bound UI showing q10/q50/q90,
  positive-CAR probability, risk/confidence, recommended horizon, cutoff,
  graph snapshot, feature hash, OOD status, and explicit unavailable states.

## Data and leakage evidence

The verified fixture is synthetic and is not a production performance claim:

- 45 rows, 15 event groups, symbols AMD/NVDA/XOM.
- Dataset hash:
  `1ffa092972707da5f0d64129187e789f48b28a944d3c3497ee3375f3fd496f7e`.
- Train/validation/test groups: 9/3/3, with no event group crossing a split.
- Train ends 2025-01-10, validation ends 2025-01-13, and test covers
  2025-01-14 through 2025-01-16.
- Scalers fit on TRAIN only; conformal and probability calibration fit on
  VALIDATION only; test remains untouched.
- Feature construction rejects bars after the declared cutoff. Subsequent bars
  are read only by the isolated training target builder.

The target is cumulative abnormal return:

```text
CAR = log(asset return) - beta_market * log(market return)
      - beta_sector * log(sector return)
```

## Measured training/evaluation

The reproducible `auto` run resolved to `linear_pinball_fallback` because the
clean environment has no LightGBM package. The frozen evaluation loaded the
artifact without retraining:

- Model version: `echo-forecast-v1-1ffa09297270`.
- Artifact hash:
  `e1065d87087263b43e7638fe71a86dbf97da00ea99e45e79927a258ba409efcf`.
- Frozen evaluation: `complete`, `retrained: false`, 45 input rows, 9 test rows.
- 1D test: MAE 0.0340886, RMSE 0.0425712, directional accuracy 0.0,
  80% interval coverage 1.0.
- 5D test: MAE 0.00487134, RMSE 0.00648995, directional accuracy 0.888889,
  80% interval coverage 1.0.
- 20D test: MAE 0.0350583, RMSE 0.0386961, directional accuracy 0.666667,
  80% interval coverage 1.0.

The report also records zero, historical-mean, exposure-only, selected-model,
and Chronos baseline rows plus graph/event/absorption/cause ablations. On this
small synthetic fixture the selected fallback loses to some simple baselines at
1D; this is retained as an honest evaluation result, not hidden by UI language.

Chronos-2 status is `BASELINE_UNAVAILABLE` in this environment because the
optional package/checkpoint is not installed locally. No Chronos metric is
claimed. The adapter follows the official `Chronos2Pipeline` interface and uses
local-only loading when explicitly invoked.

## Deterministic preview smoke

Using the last synthetic fixture row (`fixture_event_14`, XOM) and the frozen
artifact produced a `READY` result with recommended horizon `1D`, OOD status
`IN_DISTRIBUTION`, and feature hash prefix `481cf544db61`. The q10/q50/q90
values for 1D/2D/5D/10D/20D were respectively:

```text
1D  -0.175653  -0.079770   0.090990
2D  -0.040464  -0.019543   0.041123
5D  -0.012446   0.006058   0.047848
10D -0.057487   0.006220   0.110897
20D -0.093333  -0.015482   0.102625
```

These values are fixture smoke output only, not a trading recommendation.

## Verification

- Backend: `1312 passed, 90 skipped, 1 warning`.
- Backend Ruff format/check: passed.
- Frontend: `163 passed` across 20 files.
- Frontend typecheck, ESLint, and Next production build: passed.
- The only frontend repair during verification was a null-safe guard for a
  successful source response with no `items` array; it preserves the existing
  event-detail behavior.

## Day 7 boundary and risks

Day 6 does not create or mutate forecast ledger vintages. Day 7 must attach each
forecast to an immutable issuance cutoff, graph snapshot, model version, feature
version/hash, and later actual outcomes. Production use remains blocked until a
timestamped historical event/company dataset is supplied and a real artifact is
trained, evaluated against stronger baselines, and promoted through an explicit
model registry path.
