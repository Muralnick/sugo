# ADR-045: Page cache and page store in SQLite

**Status:** Accepted  
**Date:** 2026-10-29  
**Deciders:** project author  
**Implements:** ADR-006 (page store), ADR-019 (two-level per-page cache), ARCHITECTURE §10 (storage)  
**Adds dependency:** `platformdirs`

## Context

Roadmap step 5c gives the pipeline somewhere to keep pages between passes (ADR-006), so memory does not grow with document length, and a cache, so OCR is never redone and an interrupted job resumes. The cache holds document text: it is sensitive data on the user's disk, and anything read back from it must be treated as untrusted.

## Decision

### Dependency

`platformdirs` 4.13.0 (2026-10-11, the newest release at least 14 days old), MIT licence, pure Python, no dependencies; pip itself vendors it. It gives the per-user cache folder on Linux (`~/.cache/sugo`), macOS and Windows, as ADR-011 and ARCHITECTURE §10 already planned. `SUGO_CACHE_DIR` overrides it.

### Cache

- **One SQLite file**, `cache.db`, one table of entries keyed by level and key: `extraction` (pages as extracted) and `output` (pages as cleaned). The extraction level is the page store of a job and its checkpoint.
- **Keys** are SHA-256 digests of: Sugo's version, the source file's SHA-256, the page index and the engine identity (engine, model versions, DPI, OCR settings) for extraction; the extraction key and the cleaning configuration for output. Sugo's version is in every key, so fixed code never serves pages made by the old code.
- **Per-page content hash deferred** (maintainer decision): pages are keyed by the whole file's hash. Resume and OCR reuse work; a new edition of a document is extracted again in full. A per-page hash of a PDF must be computed in the isolated worker and follow the page's fonts and images; it can come later without changing the table.
- **Records** are the page's validated JSON, compressed with zlib. **Never pickle.** Reading back is untrusted: a record inflating past 64 MB, with trailing data, truncated, not JSON or failing the strict IR validation is dropped and counts as a miss. `verify()` drops every such entry.
- **Size limit** 2 GB by default, least recently used pages evicted down to 90%. Each process keeps a running total and sums the table only when it passes the limit, so writes stay at a constant cost (about 1 400 pages/s written, 2 400 read, on the reference machine).
- **Pages are not cached** when less than 512 MB of disk would remain, or when another process holds the database for more than 5 s: the job continues without the cache. A database damaged while in use is skipped the same way.
- **Rebuilt, not migrated:** a file that is not a database or has another schema version is replaced by an empty cache. ADR-019's migrations with backup apply to precious data (`registry.db`, audit), not to regenerable caches.
- **Privacy:** the cache directory is created owner-only (0700) and tightened if looser; a symbolic link, a non-directory or a directory owned by another user is refused. `PRAGMA trusted_schema = OFF`, so a planted file cannot use triggers or views to run functions SQLite marks unsafe. Log messages never carry document text, keys or file names (principle 11). An **ephemeral** cache lives in a private temporary directory deleted on close; `purge()` implements `retention_days`; `clear()` starts a new file (and repairs a damaged one). The `sugo cache stats|clean|clear|verify` commands come with the CLI (step 7).
- An import-linter contract keeps storage on the IR only: no extractors, cleaners, serializers, ports or network.

## Alternatives considered

| Alternative | Why not |
|---|---|
| Own code for platform folders | About 50 lines to keep right on three systems; `platformdirs` is the standard and tiny |
| Pickled pages | Reading a pickle runs code; a planted or damaged file would be an attack |
| One JSON file per page | Rejected in ADR-006: less crash-safe, slow on Windows |
| Content-addressed blob files now | Pages compress to a few kB; blobs wait for rendered images or audio |
| Summing the table on every write | Writes slowed from about 1 500 to 500 pages/s with 6 000 pages cached |
| Migrating old cache schemas | Everything in the cache is regenerable; a rebuild is simpler and safer |

## Consequences

- New dependency in the base install: `platformdirs`.
- Residual risks: on Windows there are no POSIX modes; the cache relies on the profile folder being private, which is the default. Deleted cache files may survive on SSDs; full-disk encryption is the real protection (ARCHITECTURE §10). Another process's writes are seen by this process's size check only when it next passes the limit, so the cache can briefly exceed it.
