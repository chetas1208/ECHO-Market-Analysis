# Day 6 Forecasting Engine

Day 6 produces an ephemeral, event-conditioned forecast preview. Day 7 owns
permanent forecast-vintage creation; the preview API never inserts or mutates
`forecast_runs` or `forecast_points`.

## Target

For asset `i`, issuance time `t`, and trading-day horizon `h`:

```text
CAR(i,t,h) = log(P_i,t+h / P_i,t)
              - beta_market * log(P_market,t+h / P_market,t)
              - beta_sector * log(P_sector,t+h / P_sector,t)
```

Targets use subsequent available NYSE sessions and are constructed only for
training/evaluation. Feature construction rejects bars after the data cutoff.
Weekends and the embedded 2025–2027 NYSE holidays are skipped.

## Features

`echo-features-v1` uses a fixed, structured feature list:

- event severity, novelty, corroboration, confidence, independent sources, and age;
- economic-channel count, signed strength, and absolute strength;
- ShockGraph exposure, confidence, path depth/count, strongest path weight/confidence,
  and direct company mention;
- Cause Engine component scores when available, otherwise explicit missing values;
- explicit one-hot Day 5 response states;
- 1m/5m/15m returns, return/volume/volatility z-scores, market/sector residuals,
  and information-absorption fields.

Raw event text is never passed to the tabular model. Missing values are imputed
with medians fitted on the training split only.
The forensic feature snapshot also retains the cutoff-estimated market and
sector betas used by the CAR target evaluator; these auxiliary values are not
model inputs until a deliberately versioned retrain.

## Splitting and leakage

Rows are sorted chronologically by event group. All rows from one event stay in
one of TRAIN, VALIDATION, or TEST; rows are never random-shuffled. The scaler is
fit on TRAIN only, conformal calibration is fit on VALIDATION only, and the
latest TEST period remains untouched.

The feature builder rejects future bars. The target builder is isolated to
training/evaluation and is the only component allowed to read subsequent bars.
Graph snapshots and canonical events used by inference are required to be
visible at `data_cutoff_at`.

## Model stack

- **Chronos-2-Small:** optional market-only baseline. The adapter uses the official
  `Chronos2Pipeline.predict_df` interface and local-only checkpoint loading. It is
  never called the event alpha model.
- **LightGBM:** optional primary quantile backend with 15 models (q10/q50/q90 ×
  1D/2D/5D/10D/20D). Conservative fixed parameters are used; there is no test
  tuning.
- **Linear pinball fallback:** deterministic local fallback when LightGBM is not
  installed. The status and artifact backend say `linear_pinball_fallback`.
- **HAR-RV:** lightweight historical-volatility context using daily, weekly, and
  monthly realized-variance regressors. It supplies risk context, not event alpha.

Quantiles are sorted after prediction to prevent crossing. `P(CAR > 0)` is a
piecewise quantile-CDF estimate and can be passed through validation-only
isotonic calibration when validation data exists.

## Calibration, OOD, and abstention

Validation absolute residuals provide an 80% conformal interval adjustment.
Training feature ranges provide a lightweight OOD detector. A forecast abstains
with `FORECAST_UNAVAILABLE` for missing artifacts, graph exposure, stale/insufficient
market history, or OOD features. No number is substituted for an unavailable
dependency.

The recommended horizon is deterministic:

```text
abs(q50) / risk * confidence - 0.0005 * trading_days
```

Information half-life is returned only when at least three positive historical
impact observations support a negative exponential decay fit; otherwise it is
`null`.

## Commands

```bash
cd backend
uv run python -m app.forecasting.train fixture \
  --output ../artifacts/data/day6-fixture.jsonl
uv run python -m app.forecasting.train train \
  --input ../artifacts/data/day6-fixture.jsonl \
  --output ../artifacts/models/forecast-bundle.json \
  --report ../artifacts/reports/day6-forecast-evaluation.json \
  --backend auto
uv run python -m app.forecasting.evaluate \
  --input ../artifacts/data/day6-fixture.jsonl \
  --artifact ../artifacts/models/forecast-bundle.json \
  --report ../artifacts/reports/day6-frozen-evaluation.json
```

The fixture is synthetic and explicitly labelled. Production artifacts must be
trained from timestamped market/event rows. Set `FORECAST_ARTIFACT_PATH` to the
frozen artifact used by the API.

## API and UI

- `POST /api/v1/forecasts/preview` returns `ForecastResult` without ledger mutation.
- `GET /api/v1/forecasting/status` reports artifact and Chronos availability.
- The existing Forecasts tab renders event/company context, all five horizons,
  q10/q50/q90, positive-return probability, recommended horizon, cutoff, graph
  snapshot, feature hash, OOD, and model diagnostics.

The UI calls the backend and has no production forecast mocks. It labels the
target as expected abnormal return and never emits BUY/SELL instructions.

## Limitations

The repository currently has no historical production event-company training
dataset or locally cached Chronos checkpoint. The clean local path therefore
exposes explicit unavailable status until real data and artifacts are installed;
the deterministic fixture exists for reproducibility tests only. Full strategy
simulation and permanent forecast-vintage creation remain Day 7 work.
