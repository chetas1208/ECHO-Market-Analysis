# Release architecture

World Monitor / replay and market data / replay feed into canonical events and
observations. ShockGraph and Cause Engine provide economic propagation and
evidence. Forecasts create immutable abnormal-return vintages. The frozen
strategy applies absorption and risk gates, ending in `ABSTAIN` or simulated
Alpaca PAPER execution.
