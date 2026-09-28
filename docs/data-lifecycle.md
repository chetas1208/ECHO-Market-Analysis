# Data lifecycle and lineage

Every derived dataset or model artifact must record its provider/source, date range or cutoff,
generation code version, configuration hash, and content hash. Forecast vintages already preserve
feature/model/graph references; new offline datasets follow the same rule.

Retention tiers:

| Tier | Examples | Policy |
| --- | --- | --- |
| Hot | current bars, provider health, queues | short operational window; bounded by the configured queue/history |
| Warm | normalized bars, event evidence, features | retained for research and reproducible replay |
| Archive | prediction ledger, trades, graph snapshots, audit/reconciliation records | append-only, backed up, never casually deleted |

Raw packets and news bodies are not retained forever by default. Offline research exports should
use a columnar format such as Parquet with ZSTD only when the dataset size justifies the added
tooling; live PostgreSQL rows are not manually compressed. The provider and source URL boundary is
untrusted input and is never rendered as executable HTML.
