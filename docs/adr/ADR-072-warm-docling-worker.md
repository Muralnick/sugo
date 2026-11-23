# ADR-072: A warm Docling worker, the first step of the shared engine

**Status:** Accepted (ADR approved 2026-11-23; maintainer decisions of 2026-11-23: the warm worker first, the full engine later; the MCP server shares a warm worker, recycled as in §2; N = 20 documents)
**Date:** 2026-11-23
**Deciders:** project author
**Implements:** ADR-071 §6 step 4 ("the shared engine, its own ADR"), first part; ADR-018 (model residency, idle unload)
**Builds on:** ADR-043 (isolated workers), ADR-071 (Docling worker), ADR-036 (network boundaries), ADR-049 (MCP server), ADR-055 (web UI), ADR-062 (shell)
**Adds dependencies:** none

## Context

The maintainer decided on 2026-11-14 that the shared engine comes before 0.3.0. The `normal` benchmark (2026-11-23, reference machine, `docs/TESTING.md`) shows why, and how much it can give:

| PDF | `lite` | `normal` today: a new Docling worker per document | `normal`, Docling already loaded |
|---|---|---|---|
| Ruled table, 1 page | 0.3 s | 11–12 s | 3.7 s |
| Report, 5 pages | 0.4 s | 14–16 s | 7.2 s |
| Two columns, 1 page | 0.3 s | 9 s | 2.3 s |

Each document pays about 4 s to import PyTorch and Docling and about 4 s to load the two models. A loaded Docling still needs about 1.4 s per page on the CPU. So keeping Docling loaded makes `normal` **2–4× faster, not 30×**: `normal` stays a slow, careful level, and the documentation must say so. The warm worker peaks at about 1.8 GB, within the 2.5 GB budget.

ADR-018's full design is a per-user engine process: a local socket or named pipe, JSON-RPC with a versioned handshake, auto-start, idle shutdown, a memory budget, a scheduler and priorities. That is several weeks of work and a new attack surface: a socket other programs can reach. Most of the speed-up does not need it. The ports that convert many documents already live long: the shell, `sugo ui`, the MCP server, and a `sugo convert` run on many files.

## Decision

### 1. A warm Docling worker inside each long-lived Sugo process

The Docling worker (ADR-071 §3) stays alive between documents in the process that started it, instead of exiting after one document. The same isolated process, the same limits and the same offline environment are used. Only its lifetime changes. Ports and lifetimes:

| Port | The worker lives |
|---|---|
| `sugo convert` / `sugo stats` with several files | for the run |
| Shell (`sugo`) | for the session |
| `sugo ui` | for the server's life |
| MCP server | for the server's life |
| `sugo convert` with one file, Python API one call | as today: one document. The API keeps it warm only inside an explicit `with sugo.Session():` (§5, deferred) |

There is no socket, no daemon and no new channel: the worker still talks only to its parent, through the same pipe.

### 2. Recycling: never more than a bounded number of documents per worker

A worker that has read many untrusted files is a risk. A crafted PDF that compromised docling-parse could leave state behind that changes, or leaks into, the next document's output. So the worker is replaced:

- after **every** failure, timeout or protocol error (never reused after one);
- after **N = 20 documents** (maintainer decision): each recycle costs about 8 s, so 20 documents spread it to about 0.4 s each;
- after **5 minutes idle**, which also returns the ~1.8 GB to the system (ADR-018: "unloaded after idle timeout").

The MCP server follows the same rule (§6).

### 3. Protocol: documents in sequence over the existing pipe

The parent sends one document at a time: a length-prefixed frame, the same framing the worker already uses for its answers. The worker answers with `Opened`, then `PageRead`... as today, then waits for the next document. The per-document size cap, time limits and the parse of every message on return (ADR-037) are unchanged. The worker never holds two documents at once. A malformed frame in either direction ends the worker.

### 4. Memory

Only one warm Docling worker per Sugo process. In `lite`, nothing changes and no worker is kept. `sugo doctor` reports the level's expected memory. The per-process address-space cap stays as set in ADR-071.

### 5. What stays for the full shared engine (later, its own ADR)

- one engine per user shared by every port, warm across separate one-shot commands;
- the local socket or pipe, its handshake and its access control;
- memory reservations, queues, priorities and the background service;
- `sugo.Session()` / `sugo.Engine()` in the Python API (ARCHITECTURE §11, by amendment of ADR-067).

These come with v0.4's background service (watcher, clipboard mode), which needs a long-running engine anyway.

### 6. The MCP server (maintainer decision, 2026-11-23)

The MCP server shares one warm worker across the agent's requests, recycled as in §2, rather than a new worker per document (about 8 s more per PDF). Every file the server opens has already passed its allowed-roots and credentials checks.

## Alternatives considered

| Alternative | Why not now |
|---|---|
| The full ADR-018 engine first | Weeks of work and a socket other local programs can reach, for a gain this step already gives the ports that need it; it stays the goal (§5) |
| Docling in Sugo's own process | Loses crash containment and hard limits on untrusted files (ADR-043) |
| Never recycle | One compromised parse could affect every later document of the session |
| Faster models or ONNX | Docling has no ONNX table model (ADR-071 context); the 1.4 s/page is the model's own cost on CPU |

## Consequences

- `normal` gets 2–4× faster in the shell, the web UI, the MCP server and multi-file conversions. One-shot single-file commands stay as today. The README states `normal`'s real speed.
- No new public contract and no new network surface. The internal worker protocol gains "next document".
- Tests: several documents through one worker; recycling after N documents, after a failure and after idle time; output identical to a fresh worker's; memory returned after idle.
- ADR-018's full engine remains planned, now scoped by §5.
