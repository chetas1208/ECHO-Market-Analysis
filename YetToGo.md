Paste matches ~95% of what's already in decisions.md, Plan.md, Milestones.md and seed.md. No new lock needed. Nothing changed on disk.

Gaps the paste exposes (docs silent or weak):

Fusion undefined. Plan lists "Forecast Fusion" but never says how it works.
D-003 target is CAR, already market/sector-adjusted.
Chronos forecasts raw return.
The paste's total = base + event is only safe if it is a no-event baseline plus excess. Otherwise beta is double-counted.
Proposed rule: LightGBM predicts CAR only. Chronos feeds the chart's implied price path and is optionally a feature. Conformal applies to CAR.
Exposure formula undefined. Day 4 says "exposure propagation formula". Paste gives Σ_paths sign × conf × e^(-λL) × Π w_k. Still needs:
max path length (suggest 3)
multi-path aggregation (suggest tanh or noisy-OR, not raw sum)
a value for λ
Trade immutability missing. D-005 freezes forecasts only. Paper and simulated positions need append-only simulated_trade rows. Fills and exits go in as separate rows.
Immutability enforcement weak. Day 7 says "cannot be updated via application code".
Stronger: DB-level REVOKE UPDATE/DELETE, plus a trigger that raises on any attempt.
Better still: a prev_hash chain, so tampering shows.
Biggest risk, in no doc: LightGBM training data.
Day 6 assumes a labeled historical event×stock→CAR dataset exists. No day builds it.
One event yields many correlated rows, so effective N is small.
Needs a backfill plan (probably Day 3–4), event-grouped purged time-split CV, and time-ordered conformal residuals.
Fallback if N is too thin: few features, monotone constraints, or a linear quantile model.
Unverified in the paste. Citations were stripped, and I haven't checked these:

Chronos-2-Small at 27.9M params / 112 MB
ModernFinBERT at 149M
the 46.8% benchmark
the "2026 JFE" paper
HERALD
Confirm the exact HuggingFace IDs and sizes before D-011 is treated as final. I can check via web search.

Which do you want?

A: Append D-033..D-037 (items 1–5) to decisions.md.
B: Start the Day 1 scaffold (FastAPI, Postgres schema with immutable ledger, frontend shell).
C: Both, A first.
I'd pick C.

Separate: caveman plugin has a statusline badge not configured yet. Say the word and I'll set it up.