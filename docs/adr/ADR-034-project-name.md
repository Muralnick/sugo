# ADR-034: Project name: Sugo

**Status:** Accepted  
**Date:** 2026-10-27  
**Deciders:** project author

## Context

The working name `tsp` conflicts with Debian's task-spooler command and is taken on PyPI. The author wanted a short, memorable name; Italian names give a distinctive identity consistent with Italian priority.

## Decision

Name **Sugo** ("il sugo del discorso" = the gist; a sauce is reduced to concentrate flavour). Command `sugo`, config `sugo.toml`, `[tool.sugo]`, packs `sugo-pack-*`. Free on PyPI as of 2026-10-27. Tagline: "Documents, reduced."

## Alternatives considered

| Alternative | Why not |
|---|---|
| Succo | Rejected by the author |
| Passata | Also means "outdated" in Italian |
| Ristretto | Conflicts with Xfce's image viewer command |
| Ragù | Taken on PyPI |

## Consequences

- Still to verify: Debian/Ubuntu command conflicts, GitHub, trademarks.
- Reserve on PyPI with the first real release.
