# Model operations policy

`artifacts/models/registry.json` is the lightweight registry. A record contains model name/version,
training cutoff/date, dataset hash, metrics, artifact path/hash, and one of `EXPERIMENTAL`,
`VALIDATED`, `ACTIVE`, or `RETIRED`.

Promotion is explicit:

```text
train -> evaluate -> compare -> approve -> ACTIVE
```

No request path promotes a latest artifact. Existing forecast vintages retain the exact model,
feature, graph, and content references used at issuance. Online weight updates are prohibited while
paper execution is enabled. Drift monitoring should compare forecast error, directional accuracy,
interval coverage, feature distributions, calibration, hit rate, profit factor, drawdown, and trade
frequency against the training baseline; one bad day enters WATCH rather than triggering an
automatic retrain.
