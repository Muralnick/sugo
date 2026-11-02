# ADR-055: Local web interface for v0.1 (`sugo ui`)

**Status:** Accepted (maintainer decisions of 2026-11-01)  
**Date:** 2026-11-01  
**Deciders:** project author  
**Implements:** ADR-015 (ports: local web UI), ADR-022 (web UI contract), ADR-036 (local networking only in ports), THREAT_MODEL E, ARCHITECTURE §12 "Web UI"  
**Updates:** ROADMAP (a minimal web UI moves into v0.1), ARCHITECTURE §12 (the standard library server, decision 1)  
**Adds:** CLI command `sugo ui`; error code `WEB_REQUEST_REFUSED`

## Context

On 2026-11-01 the maintainer asked for a graphical interface in v0.1. The ROADMAP had left it for after v0.5: v0.1 has only the command line and the MCP server.

The design is already in place:
- the web UI is one of the ports over the core (ADR-015);
- ARCHITECTURE §12 describes a local HTTP server on `127.0.0.1`, with a session token in the opening URL, `Host` and `Origin` checks, no CORS, Server-Sent Events for progress, drag and drop, and token counters per provider;
- THREAT_MODEL E names the attacker: a website open in the same browser that tries to reach the local server, by cross-site requests or by DNS rebinding;
- ADR-036 already allows loopback servers in `sugo.ports`.

What is missing is the v0.1 scope, the server library and the exact protections. A local server is a new attack surface: a page on any website can send requests to `127.0.0.1`, and a document's text is shown in a browser, where text can become code if it is inserted as HTML.

## Decision

### 1. Server library (maintainer decision, 2026-11-01: option A, the standard library)

| Option | For | Against |
|---|---|---|
| **A. Sugo's own small server on the standard library (`http.server`, `ThreadingHTTPServer`)**, recommended | No new dependency, so no 14-day wait and no new licences. Same choice as the MCP server, which implements its protocol itself (ADR-049). Only what Sugo uses: about five routes, one user, loopback only. | Sugo writes the request checks itself (size, headers, routing); `http.server` is not meant for public servers. Loopback-only use with every check below makes that acceptable. OpenAPI is not generated. |
| B. FastAPI with Uvicorn, as ARCHITECTURE §12 says | OpenAPI generated from the operations' models, mature request handling. | About six new packages (FastAPI, Starlette, Uvicorn, h11, anyio and their dependencies), each needing the licence and 14-day checks. The server reads uploads through `python-multipart`, one more package. |

**Maintainer decision, 2026-11-01:** option A. ARCHITECTURE §12 names the standard library server for v0.1. FastAPI can come with the full UI after v0.1, through its own ADR, if the API grows.

### 2. Scope for v0.1 (maintainer decision, 2026-11-01: the list below)

**Maintainer decision, 2026-11-01:** the minimal list below, with the items under "Left for later" after v0.1.

`sugo ui` starts the server and opens the page in the default browser (`--no-browser` prints the address instead). The page:

- takes a file by drag and drop or through a file picker. The formats are those of `sugo convert`: PDF, DOCX, XLSX, PPTX, PNG, JPEG, WEBP and XML;
- shows the Markdown, with a button to copy it and one to save it as `.md`;
- shows the tokens before and after, for each LLM provider (the `stats` operation), and how many blocks each cleaner removed, with its name (`hidden_text`, `headers_footers`, …);
- shows a refused file as the CLI does: the stable code, the message and the hint;
- speaks Italian or English, following `ui.language` (ADR-052).

**Maintainer decision, 2026-11-01 (after trying the first version):** the page also gets:
- a clearer look: the token counts as large figures with a before/after bar, and the Markdown beside the details on a wide screen;
- a **Settings** panel with what Sugo already does: the interface language, the languages of the text rules (`general.languages`), removing tracking parameters (`cleaning.strip_tracking_urls`), and chunks on or off with their size (`chunking.max_tokens`). Defaults come from the user's configuration. The page sends the choices with each conversion, in headers checked by the server like any other input (unknown values are refused). The browser remembers them for this computer (local storage); the server never writes them to disk, and `config.toml` stays the base;
- **chunks for RAG**, as `sugo convert --chunks`: shown on the page and saved as `.jsonl`;
- a **Questions** page (FAQ) about what Sugo does, privacy, formats, tokens and chunks.

Work profiles (ADR-021) are not anticipated: they stay in v0.3, and the Settings panel holds only what v0.1 already has.

Left for later:
- a side-by-side preview of the original;
- the list of each removed block with its reason (the `explain` operation);
- progress by Server-Sent Events (in v0.1 the page shows that the conversion is running);
- several files at once;
- work profiles (ADR-021).

### 3. Protections (THREAT_MODEL E)

| Threat | Protection |
|---|---|
| Another machine on the network | The server listens only on `127.0.0.1`, on a port the system chooses; there is no option to listen elsewhere. |
| A website in the browser sends requests to the server (CSRF) | A random token of 32 bytes (`secrets.token_urlsafe`) is made at every start. It is placed in the URL fragment (`#token=…`), which the browser never sends to a server, never writes into `Referer` and never shows to another site. The page reads it and sends it in an `X-Sugo-Token` header on every API request; the server compares it in constant time. A custom header makes the browser ask the server first (a CORS preflight), and the server never allows another origin, so a foreign page cannot send it. |
| DNS rebinding: a site's name made to point at `127.0.0.1` | Every request must carry `Host: 127.0.0.1:<port>` or `localhost:<port>`, else it is refused. API requests must also carry an `Origin` equal to the server's own; requests without one are refused. |
| Document text turned into code in the page (XSS) | The Markdown, file names, messages and reasons are always inserted as text (`textContent`), never as HTML; v0.1 does not render Markdown as HTML. Every response sends a strict `Content-Security-Policy` (`default-src 'self'`, no inline script, `frame-ancestors 'none'`), `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer` and `Cache-Control: no-store`. |
| Settings sent by the page | Each option is one header, at most once, checked against the known values (interface languages, language packs, `true`/`false`, a chunk size within the CLI's bounds); anything else is refused. The server keeps no state between conversions and writes nothing to disk. |
| Reading files from the disk | The API takes only the bytes of the file the user drops. It has no path parameter and lists no folder, so there is no path to traverse, unlike the MCP server's allowed roots. |
| Oversized uploads | `Content-Length` is required and checked against the file size limits before the body is read (200 MB, as for Office and PDF); chunked uploads are refused. One conversion runs at a time; a second request gets `WEB_REQUEST_REFUSED`. The page also checks the size before sending, so the user sees why. A slow client is cut off by a socket timeout. |
| Pages loaded from the internet | Page, style and script are files inside the Sugo package, with no CDN, external font or analytics: the page works offline and sends nothing out. |
| Logs | The server's access log is off. As everywhere, Sugo never logs document content or file names (CLAUDE.md). |

The server stops when the command is stopped (Ctrl+C). An import-linter contract keeps `http.server` inside `sugo.ports.web`.

### 4. Error model

A refused file answers with the error model of ADR-022: HTTP status and the same JSON as the CLI's `--json` (`code`, `message`, `hint`, `details`). The new stable code `WEB_REQUEST_REFUSED` covers requests refused by the protections above (wrong token, host or origin, a missing size, a second conversion while one is running), with HTTP 403, 411, 413 (a size over the limit) or 409. Its message never says which check failed, so it gives a probing page no hint.

### 5. When

After ROADMAP step 8 (benchmarks) and before step 9 (PyPI): about two or three working days, with tests, code review and security review. The pre-release `v0.1.0a1` can come before the UI.

## Alternatives considered

| Alternative | Why not |
|---|---|
| Keep the UI for after v0.5, as the ROADMAP said | Maintainer decision of 2026-11-01: wanted in v0.1. |
| A desktop program (Qt, Tk, a webview) | A new graphical toolkit, larger, different on each system; the browser is already there. |
| The token in the URL query or a cookie | A query ends up in browser history, logs and `Referer`; a cookie is sent by the browser on its own, which is what cross-site requests rely on. A fragment plus a custom header is sent only by Sugo's page. |
| Rendering Markdown as HTML in v0.1 | A sanitiser would be needed against document text turned into code; plain text is enough to read and copy. |

## Consequences

- New CLI command `sugo ui` (additive) and new error code `WEB_REQUEST_REFUSED`; Italian catalog entries for the page.
- No new dependency (option A).
- A new attack surface, limited to the local user's browser; a security review is required before merging, and THREAT_MODEL E gets the token-in-fragment and preflight details.
- Residual risks:
  - another program run by the same user can reach the server, as it can read the user's files anyway;
  - a malicious browser extension can read the page, and the token with it.
