# Day 9 Audit

Date: 2026-09-21

## Strategy and artifacts

- Frozen candidate: `echo-rp-v1`.
- Config hash: `128191d8304211045b29cb8b7dde187286242428f0e68b5e1e99efe9b06b5602`.
- Conviction handoff: `artifacts/strategy/conviction-final.md` and
  `artifacts/strategy/conviction-prompt.txt`.
- Existing backtest run: `0e4a33a922f147aefc17`; no historical artifact was
  rewritten.

## Execution

- `DISABLED` is the default and `LIVE` is rejected.
- `REPLAY` uses a deterministic in-memory adapter for dry-run and parity tests.
- `PAPER` uses `alpaca-py` only when credentials are configured and
  `ALPACA_PAPER=true`.
- Decision state, freshness, forecast validity, risk, portfolio limits,
  shortability, buying-power/provider health, idempotency, and kill switch are
  checked before submission.
- Order intents, execution events, fills, and reconciliation records are
  append-only under migration `0009_paper_execution`.

## Verification status

Local replay/dry-run and duplicate-submission tests are implemented. Alpaca
account/order/fill verification is **NOT VERIFIED** because credentials and an
explicit paper-order authorization are absent. No live or paper order was placed.

## Limitations

The checked-in dataset is synthetic, restart recovery is represented by the
append-only database contract but not exercised against an external broker, and
rolling 10-day market distributions remain blocked by the missing historical
event archive. Day 10 is intentionally not implemented.
