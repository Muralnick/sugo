# ADR-018: Process model, shared engine and memory budget

**Status:** Accepted  
**Date:** 2026-10-27  
**Deciders:** project author

## Context

Python runs one computation per process; native libraries can crash on malformed files; running CLI, UI and MCP simultaneously with separate models would triple memory on 8 GB machines.

## Decision

Isolated worker processes (light, model, single GPU worker) started with `spawn`; one shared engine per user reached via a local socket or named pipe, auto-start and idle shutdown, plus standalone mode. Reservation-based memory budget with bounded queues, monitoring and graceful degradation (parallelism → DPI → model size). Adaptive render DPI. Pages grouped by backend so each model loads once. Total threads ≤ physical cores. Batched GPU queue with CPU/GPU overlap and FP32 fallback. Interactive priority preempts background at page boundaries. Warm clipboard worker unloaded when idle. Optional battery mode; low OS priority for background jobs.

## Alternatives considered

| Alternative | Why not |
|---|---|
| Threads in one process | No crash containment, no hard timeouts |
| Per-port engines | Memory multiplied |

## Consequences

- Engine protocol is internal but versioned (ADR-022).
