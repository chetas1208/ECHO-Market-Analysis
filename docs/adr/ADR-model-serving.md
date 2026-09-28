# ADR: Optional model serving boundary

Status: DEFER PROCESS SPLIT; KEEP LAZY LOCAL LOADING (Day 11)

## Context

ModernFinBERT and Chronos are optional. ModernFinBERT is lazy and local-files-only when enabled;
Chronos reports unavailable when its package/checkpoint is absent. The registered local forecast
artifact is a deterministic linear pinball fallback. The market feature engine is already moved
to a worker thread.

## Decision

Keep optional models in-process and lazy for the current replay/demo deployment. Do not claim a
worker boundary, ONNX speedup, quantization gain, or warm latency until a real model is loaded and
measured. If model RSS or warm latency breaches the documented budget, isolate that model in a
bounded worker process before considering container orchestration.

## Consequences

Startup remains safe without model packages or credentials. The registry distinguishes ACTIVE
from EXPERIMENTAL and unavailable models. Model promotion remains explicit and never follows a
latest-artifact discovery automatically.
