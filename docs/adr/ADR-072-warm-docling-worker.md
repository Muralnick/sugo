# ADR-072: A warm Docling worker, the first step of the shared engine

**Status:** Accepted (ADR approved 2026-11-23; maintainer decisions of 2026-11-23: the warm worker first, the full engine after 0.3.0; the MCP server uses a fresh worker per document; N = 20 documents)
**Date:** 2026-11-23
**Deciders:** project author
**Implements:** ADR-071 §6 step 4 ("the shared engine, its own ADR"), first part; ADR-018 (model residency, idle unload)
**Builds on:** ADR-043 (isolated workers), ADR-071 (Docling worker), ADR-036 (network boundaries), ADR-049 (MCP server), ADR-055 (web UI), ADR-062 (shell)
**Amends:** ADR-071 §6 and its decision of 2026-11-14 ("the shared engine before 0.3.0"): 0.3.0 ships this warm worker; the full per-user engine moves after it (§5)
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
| Shell (`sugo`) | while it is in use, as `sugo ui` |
| `sugo ui` | while it is in use: stopped after 5 minutes idle (§2), started again by the next PDF at `normal` |
| MCP server | never warm: a fresh worker per document (§6) |
| `sugo convert` with one file, Python API one call | as today: one document. The API keeps it warm only inside an explicit `with sugo.Session():` (§5, deferred) |

Ports and the Python API opt in explicitly; anything else keeps one worker per document. There is no socket, no daemon and no new channel: the worker still talks only to its parent, through the same pipe.

### 2. Recycling: never more than a bounded number of documents per worker

A worker that has read many untrusted files is a risk. A crafted PDF that compromised docling-parse could leave state behind that changes, or leaks into, the next document's output. So the worker is replaced:

- after **every** failure, timeout or protocol error (never reused after one);
- after **N = 20 documents** (maintainer decision): each recycle costs about 8 s, so 20 documents spread it to about 0.4 s each;
- after **5 minutes idle**, which also returns the ~1.8 GB to the system (ADR-018: "unloaded after idle timeout").

The MCP server does not reuse a worker at all (§6).

### 3. Protocol: documents in sequence over the existing pipe

The parent sends one document at a time: a length-prefixed frame, the same framing the worker already uses for its answers. The worker answers with `Opened`, then `PageRead`... as today, then waits for the next document. The per-document size cap, time limits and the parse of every message on return (ADR-037) are unchanged. The worker never holds two documents at once. A malformed frame in either direction ends the worker.

### 4. Memory

Only one warm Docling worker per Sugo process. In `lite`, nothing changes and no worker is kept. The per-process address-space cap stays as set in ADR-071.

**Known limit of this step:** the 2.5 GB budget holds per Sugo process, not per user. A shell and `sugo ui` converting PDFs at `normal` at the same time can each hold a worker of about 1.5–1.8 GB. The idle stop (§2) bounds how long that lasts. The documentation says so. A per-user reservation needs the shared engine (§5), which is the place for it.

### 5. What stays for the full shared engine (later, its own ADR)

- one engine per user shared by every port, warm across separate one-shot commands;
- the local socket or pipe, its handshake and its access control;
- memory reservations, queues, priorities and the background service;
- `sugo.Session()` / `sugo.Engine()` in the Python API (ARCHITECTURE §11, by amendment of ADR-067).

These come with v0.4's background service (watcher, clipboard mode), which needs a long-running engine anyway.

### 6. The MCP server: a fresh worker per document (maintainer decision, 2026-11-23)

An agent's requests can mix files of very different trust, and its answers feed straight back into the agent. A crafted PDF that compromised docling-parse undetected, past the allowed-roots and credentials checks, could alter or poison the next files' results while the worker lives. So the MCP server never reuses a Docling worker: each PDF at `normal` gets a fresh one, as before this ADR, at about 8 s more per PDF. The shell, `sugo ui` and multi-file conversions keep the warm worker: there the person chose the files in front of them.

## Alternatives considered

| Alternative | Why not now |
|---|---|
| The full ADR-018 engine first | Weeks of work and a socket other local programs can reach, for a gain this step already gives the ports that need it; it stays the goal (§5) |
| Docling in Sugo's own process | Loses crash containment and hard limits on untrusted files (ADR-043) |
| Never recycle | One compromised parse could affect every later document of the session |
| Faster models or ONNX | Docling has no ONNX table model (ADR-071 context); the 1.4 s/page is the model's own cost on CPU |

## Consequences

- `normal` gets 2–4× faster in the shell, the web UI and multi-file conversions. The MCP server and one-shot single-file commands stay as today. The README states `normal`'s real speed and the memory limit of §4.
- No new public contract and no new network surface. The internal worker protocol gains "next document".
- Tests: several documents through one worker; recycling after N documents, after a failure and after idle time; output identical to a fresh worker's; memory returned after idle.
- ADR-018's full engine remains planned, now scoped by §5.
