# ADR-021: Guided setup, work profiles and decision cards

**Status:** Accepted  
**Date:** 2026-10-27  
**Deciders:** project author

## Context

Installing everything wastes gigabytes, increases attack surface and confuses users. pip installs before the program can ask questions.

## Decision

Two-step install: small base, then `sugo setup`. Terminology: level / profile / recipe. Seven official work profiles (`personal`, `dev`, `rag`, `office`, `legal`, `research`, `full`), combinable, most protective wins. Phone-style setup: one toggle per screen with a four-part card (what it does, if yes, if no, good to know) and size; summary with "you will / will not be able to". Profiles and cards are data files; sizes measured in CI. CPU-only PyTorch without an NVIDIA GPU. About eight tested packs; `--advanced` for untested combinations; answers file for companies; just-in-time installs with confirmation, never from MCP.

## Alternatives considered

| Alternative | Why not |
|---|---|
| Install everything | Gigabytes and dependencies most users never need |
| Unlimited fine-grained modules | Untestable combinations |

## Consequences

- Install in a dedicated environment (`uv tool`/`pipx`) because Debian-based systems block system-wide pip.
