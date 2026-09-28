# ADR: Rust optimization decision gate

Status: DEFER (Day 11)

## Context

The current graph propagation and feature pipeline are bounded, deterministic Python code. The
market feature engine already runs in a worker thread so provider ingestion and API health do not
share the same blocking call. Rewriting the Python core before profiling would increase review and
serialization risk.

## Decision

Defer Rust. First retain repeatable benchmark baselines in `artifacts/benchmarks/day11/` and add a
Rust hotspot only if a measured production workload identifies normalization, feature aggregation,
graph traversal, or serialization as the dominant bottleneck.

## Consequences

There is no FFI, build toolchain, or second implementation to operate today. Any future hotspot
must preserve exact output fixtures, stable hashes, and a Python fallback before promotion.
