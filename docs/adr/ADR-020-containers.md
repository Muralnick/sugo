# ADR-020: Containers: folders, archives and emails; plan first

**Status:** Accepted  
**Date:** 2026-10-27  
**Deciders:** project author

## Context

Users upload folders and archives; archives are a classic attack vector; emails and PDFs also carry files.

## Decision

A container abstraction (folder, zip, tar, email, PDF attachments, PEC) with provenance notation (`archive.zip!/path/file.pdf`). Recursive scan with filters and `.sugoignore`; content-based type detection; hash deduplication; batch fault tolerance; plan before large jobs (`sugo plan`). Archive limits on real decompressed bytes, ratio, nesting (default 2, max 3), entry count; hashed extraction names; symlinks and special files rejected; legacy filename encodings; passwords asked, never brute-forced. MCP: allowed roots, fixed exclusions, plan above threshold.

## Alternatives considered

| Alternative | Why not |
|---|---|
| Per-format special cases | Duplicated logic, inconsistent limits |

## Consequences

- Per-entry caching; RAR unsupported; 7z via optional pack.
