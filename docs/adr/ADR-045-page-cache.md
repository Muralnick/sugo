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
- **Keys** are SHA-256 digests of: a fingerprint of Sugo's own source code, the source file's SHA-256, the page index and the engine identity (engine, model versions, DPI, OCR settings) for extraction; the extraction key and the cleaning configuration for output. The code fingerprint (a digest of every `.py` file of the package, computed once per process in a few milliseconds) means fixed code never serves pages made by the old code; the package version alone changes only on releases, never in a development checkout.
- **Per-page content hash deferred** (maintainer decision): pages are keyed by the whole file's hash. Resume and OCR reuse work; a new edition of a document is extracted again in full. A per-page hash of a PDF must be computed in the isolated worker and follow the page's fonts and images; it can come later without changing the table.
- **Records** are the page's validated JSON, compressed with zlib. **Never pickle.** Reading back is untrusted: a record inflating past 64 MB, with trailing data, truncated, not JSON or failing the strict IR validation is dropped and counts as a miss. `verify()` drops every such entry. A page whose JSON exceeds 64 MB is not stored, since it could never be read back.
- **Size limit** 2 GB by default, least recently used pages evicted down to 90%. **Pages used in the last 24 hours are never evicted:** the cache is also the page store, and a running job (here or in another process) must find its own pages in its later passes. The limit is therefore soft while large jobs run. A hit refreshes a page's last use only when it is older than 10 minutes, so reading a cached document does not write once per page.
- **Constant costs:** the record is the last column and a covering index holds use time and size, so size totals and eviction never read records. Each process keeps a running total and sums the index only when it passes the limit. Measured on the reference machine: about 1 500 pages/s written, 5 000 read, 2 ms to open.
- **Disk space:** incremental auto-vacuum and a write-ahead log cut back to 64 MB give the space of evicted, purged or cleared pages back to the file system.
- **Pages are not cached** when less than 512 MB of disk would remain, when the cache folder is unreachable, or when another process holds the database for more than 5 s: the job continues without the cache. A database damaged while in use is skipped the same way.
- **Concurrent processes:** opening a current cache only reads, so it never waits for a writer. If the database is locked or read-only at open, `CacheUnavailableError` tells the caller to run without a cache, and the file is left untouched. Files are deleted only when SQLite reports them damaged or not a database; `clear()` deletes rows, never the file another job may be using.
- **Rebuilt, not migrated:** a file that is not a database is replaced by an empty cache, and a cache with another schema version is emptied and compacted. ADR-019's migrations with backup apply to precious data (`registry.db`, audit), not to regenerable caches.
- **Privacy:** the cache directory is created owner-only (0700) and tightened if looser; a symbolic link, a non-directory or a directory owned by another user is refused. `PRAGMA trusted_schema = OFF`, so a planted file cannot use triggers or views to run functions SQLite marks unsafe. Log messages never carry document text, keys or file names (principle 11). An **ephemeral** cache lives in a private temporary directory deleted on close; `purge()` implements `retention_days`; `clear()` empties the cache (and replaces a damaged file). The `sugo cache stats|clean|clear|verify` commands come with the CLI (step 7).
- An import-linter contract keeps storage on the IR only: no extractors, cleaners, serializers, ports or network.

## Alternatives considered

| Alternative | Why not |
|---|---|
| Own code for platform folders | About 50 lines to keep right on three systems; `platformdirs` is the standard and tiny |
| Pickled pages | Reading a pickle runs code; a planted or damaged file would be an attack |
| One JSON file per page | Rejected in ADR-006: less crash-safe, slow on Windows |
| Content-addressed blob files now | Pages compress to a few kB; blobs wait for rendered images or audio |
| Summing the table on every write | Writes slowed from about 1 500 to 500 pages/s with 6 000 pages cached |
| Sugo's package version in the keys | Unchanged between releases and in development: fixed code would serve stale pages |
| A strict size limit | Would evict the early pages of a running job larger than the limit, so its later passes would redo OCR |
| Migrating old cache schemas | Everything in the cache is regenerable; a rebuild is simpler and safer |

## Consequences

- New dependency in the base install: `platformdirs`.
- Residual risks: on Windows there are no POSIX modes; the cache relies on the profile folder being private, which is the default. Deleted cache files may survive on SSDs; full-disk encryption is the real protection (ARCHITECTURE §10). Another process's writes are seen by this process's size check only when it next passes the limit, so the cache can briefly exceed it; pages used in the last day also stay past it.
