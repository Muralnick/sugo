# ADR-015: One core, five ports

**Status:** Accepted  
**Date:** 2026-10-27  
**Deciders:** project author

## Context

Sugo serves everyday users, developers, AI agents and servers, each with a different natural interface.

## Decision

Python API, CLI with a Claude Code-style shell, local web UI, MCP server, background service (clipboard, watcher, tray). Each port is a thin layer over the same operations.

## Alternatives considered

| Alternative | Why not |
|---|---|
| Native desktop GUI | Heavier, different per OS |
| CLI only | Excludes everyday users |

## Consequences

- Wayland global shortcuts via the desktop portal, manual fallback.
