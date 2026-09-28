# Day 9 Paper Execution

ECHO has one execution interface with two safe providers: `ReplayExecutionProvider`
for deterministic dry-run parity and `AlpacaPaperExecutionProvider` for Alpaca
paper accounts. The default mode is `DISABLED`; `LIVE` is rejected at settings
validation and by the adapter. `ALPACA_PAPER=true` is mandatory.

Only a structured `PaperDecision` with state `PAPER_TRADE` can produce an
`OrderIntent`. The execution service validates allowed symbols, fresh market data,
valid forecast, risk/portfolio limits, shortability, account/provider health,
duplicate idempotency key, daily loss, and kill-switch state. No manual symbol/
quantity order endpoint exists.

Order intents are keyed by a deterministic hash of decision, forecast, strategy,
symbol, side, and decision identity. Repeated requests return the same intent and
cannot submit a second order. Provider order IDs, status transitions, fills, and
reconciliation observations are stored in append-only Day 9 tables. Simulation
fills and Alpaca fills remain separate sources.

Missing credentials leave the application healthy with execution status
`UNCONFIGURED`; historical replay remains available. `make paper-trade` only
checks the explicitly enabled PAPER profile and never submits an order. The
dry-run path creates/validates an intent without a broker call.

The current API exposes `/api/v1/execution/status`, `/api/v1/paper/account`,
`/api/v1/paper/positions`, `/api/v1/paper/orders`, and the guarded
`POST /api/v1/paper/execute/{decision_id}`. `/api/v1/execution/reconcile` reports
broker/local order mismatches as `DEGRADED` rather than silently correcting them.
