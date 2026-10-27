# ADR-036: Network access boundaries

**Status:** Accepted  
**Date:** 2026-10-27  
**Deciders:** project author  
**Amends:** principle 1 in `PRINCIPLES.md`, ADR-016, ADR-029

## Context

Principle 1 said that only the sources module touches the network. The design itself contradicts that: the web UI serves on `127.0.0.1` (ADR-015), the shared engine talks to its clients over a Unix socket or named pipe (ADR-018), model downloads need HTTPS (ADR-013) and guided setup installs packs (ADR-021). Leaving the rule as written would force silent exceptions; dropping it would lose the guarantee that matters: document content never leaves the machine.

## Decision

Network use is split into two kinds, each with its own boundary.

| Kind | What it covers | Allowed in |
|---|---|---|
| Local networking | Loopback servers (`127.0.0.1`, `::1`), inter-process channels | `sugo.ports`, `sugo.core.engine` |
| Outbound internet | Any connection that can leave the machine | Only through the gateway `sugo._internal.net` |

- **The gateway** `sugo._internal.net` is the only module that may import network client libraries. It enforces offline mode, blocks private and link-local addresses (SSRF protection), and logs every request without content or file names (principle 11).
- **Gateway callers** are limited to `sugo.sources` (ADR-016), `sugo.models` (model downloads, ADR-013) and `sugo.setup` (pack installation, ADR-021). Every call happens only on explicit request; MCP can never trigger one (principle 10).
- **Principle 1** now reads: document content never leaves the machine through Sugo; outbound internet access goes only through a single gateway, only for sources, model downloads and pack installation, and only on explicit request; local networking is limited to ports and the engine.

### Enforcement

| Rule | Tool |
|---|---|
| Client libraries (`ssl`, `ftplib`, `smtplib`, `imaplib`, `poplib`, `xmlrpc`, `requests`, `httpx`, `urllib3`, `aiohttp`, `websockets`) only in the gateway | import-linter |
| Socket and server libraries (`socket`, `socketserver`, `http`) only in ports, engine and gateway | import-linter |
| `sugo._internal.net` imported only by sources, models and setup | import-linter |
| `urllib.request` and `http.client` banned, including in ports and engine; the gateway marks each allowed import with `# noqa: TID251` | ruff `TID251` |

import-linter can only forbid whole top-level packages, hence the ruff ban for the client submodules of `urllib` and `http` (whose other submodules, such as `urllib.parse` and `http.HTTPStatus`, are harmless).

## Alternatives considered

| Alternative | Why not |
|---|---|
| Keep "network only in sources" | Contradicted by the web UI, engine channel, model downloads and setup |
| Each caller uses network libraries directly | Offline mode and private-address blocking would be reimplemented, and one forgotten check would break principle 1 |
| No static rule, runtime guard only | Mistakes found by users instead of CI |

## Consequences

- Residual risk: `asyncio` (`open_connection`) and `multiprocessing.connection` can open sockets without importing a banned module. They are too widely used to forbid; review must check them, and the runtime network guard (ARCHITECTURE §18) remains the second line of defence.
- Residual gap in the gateway contract: import-linter does not check a module against a forbidden module nested inside it, so the top-level `sugo/__init__.py` and other `sugo._internal` modules are not covered; review must check them.
- New gateway callers or new local-networking packages need an amendment to this ADR.
- Changing principle 1 requires a public discussion on GitHub (`PRINCIPLES.md`); no version has been released yet, so no major version bump is needed.
