# ADR-059: Bring the web UI level with the command line

**Status:** Accepted (maintainer decision, 2026-11-07)
**Date:** 2026-11-07
**Deciders:** project author
**Amends:** ADR-055 (web UI scope: several items move out of "Left for later")
**Implements:** ADR-056 (receipt and verify), ADR-022 (web UI contract), THREAT_MODEL E
**Adds dependencies:** none
**Adds:** API routes `/api/verify` and `/api/doctor`; request headers for the receipt, the file name and the cache; no new error code

## Context

The maintainer's first hands-on test (2026-11-07) found the web page the weakest part of Sugo for a user: features added after ADR-055 (the conversion receipt and `sugo verify`, ADR-056) exist only on the command line, and so do several older ones (`sugo clip`, `sugo doctor`, `--no-cache`, several files with `-o`).

**Maintainer decision, 2026-11-07:** add to the page every function the command line has, in particular: the receipt with the detail of each removal and edit, receipt verification, pasting a screenshot, several files at once, a "no cache" setting and the installation check.

Not added, and why:
- `--front-matter`: not chosen by the maintainer on 2026-11-07; it can be added later as one more setting.
- `sugo mcp`: it serves AI agents over stdio, not people; the page has nothing to show for it.
- `--json`: the page already receives JSON; it is the API's format.

## Decision

Everything below keeps every protection of ADR-055 §3 unchanged: loopback only, token in the URL fragment and the `X-Sugo-Token` header, `Host` and `Origin` checks, strict Content-Security-Policy, text inserted only with `textContent`, one conversion at a time, no path parameter, nothing written to disk by the server, no external resources. Every new route and header goes through the same checks, and anything unknown, repeated or out of bounds is refused with `WEB_REQUEST_REFUSED`.

### 1. Receipt and its detail

- The page gets a setting **Receipt** (off by default, as `--receipt`). When on, the page sends `X-Sugo-Receipt: true`, the server converts with `receipt=True` and adds a `receipt` object to the response, the same object `sugo convert --json --receipt` prints.
- The page shows the receipt as three lists: **removed** blocks (page, block type, cleaner, reason, original text), **edited** text (page, cleaner, kind, reason, before and after) and **flagged** blocks (page, flags, confidence). This is the "removal list" ADR-055 left for later. Every value is inserted as text.
- A button saves `NAME.receipt.json`, written as the command line writes it (ADR-056, and indented if ADR-058 is accepted).
- The count of **edits** per cleaner (`Conversion.edited`) is shown next to the count of removals, which the page already shows.

**File name.** A receipt records its `source`; on the command line it is the path as typed. The page sends the file's **name only** (never a path; the browser does not give one) in `X-Sugo-Name`, percent-encoded because HTTP headers carry only ASCII. The server decodes it and refuses it if it is longer than 255 characters, contains `/`, `\`, control characters, or is `.` or `..`. It is used only as `source` and for the output file names; it is never logged (CLAUDE.md). Without the header, `source` is empty, as for `pipeline.convert` on bytes.

### 2. Verifying a receipt

A **Verify** section takes two files: the document and its receipt. The page sends them in one `POST /api/verify`:

- body: the receipt bytes followed by the document bytes;
- `X-Sugo-Receipt-Length`: how many of the body's bytes are the receipt (digits only, at most 50 MB, the limit of an XML file); `Content-Length` must be at least that, and the document part follows the usual input limit (200 MB).

The server does what `sugo verify` does (ADR-056), with the same code: it parses the receipt with the strict model, re-converts the document with the receipt's own `languages` and `strip_tracking_urls`, and answers with the same JSON as `sugo verify --json` (`match`, `version_drifted`, `differences`, without document text). A receipt for another edition of the file answers `FILE_CHANGED`; an invalid receipt answers `RECEIPT_INVALID`, both existing codes (HTTP 422). The page shows "the conversion is unchanged" or the list of differences, and the version warning when `version_drifted` is true.

Multipart form data is not used: the standard library no longer parses it (`cgi` was removed in Python 3.13), and a length header is simpler to check.

### 3. Pasting a screenshot

Pressing Ctrl+V (Cmd+V on macOS) on the page, or a **Paste** button, converts the image in the clipboard, as `sugo clip` does. This happens entirely in the page: it reads the image from the browser's paste event and sends its bytes to `/api/convert` like a dropped file, named `clipboard.png`. No new server route. The **Paste** button uses the browser's clipboard API, which asks the user's permission; Ctrl+V does not need it. Text pasted on the page is ignored, as `sugo clip` ignores it.

### 4. Several files at once

- The page accepts several files dropped or picked together, at most **50** per batch, and converts them **one after the other**, each with its own `/api/convert` request. The server is unchanged: it still converts one file at a time, so its limits and protections apply to each file. A file that fails does not stop the others, as on the command line.
- The page lists the files with their state (waiting, converting, done, refused with its code) and shows each result when clicked.
- **Save all** saves one `.zip` with `NAME.md` for each file, plus `NAME.jsonl` and `NAME.receipt.json` when chunks or receipts are on. The page builds the ZIP itself in a few dozen lines of script, uncompressed (the "stored" method), so no library is added. Names inside the ZIP are the file names without their extension, stripped of path separators and control characters; two files that would get the same name (`report.pdf` and `report.png`) get `report.md` and `report (2).md` instead of being refused, since there is no folder of inputs to overwrite.
- The results stay only in the page's memory and disappear when it is closed.

### 5. No cache

The Settings panel gets **Keep a cache on disk** (on by default when `storage.cache` is `persistent`). When off, the page sends `X-Sugo-Cache: off` and the server converts with the cache disabled, as `--no-cache`. Only `off` is accepted; the setting can turn the cache off, never on against the configuration.

### 6. Installation check

A **Check installation** button in the Settings panel calls `POST /api/doctor` with an empty body (token, host and origin checked like the conversion route; POST because browsers do not always send `Origin` with a same-origin GET, and the server requires it) and shows the same checks as `sugo doctor --json`: name, status and message of each. The route runs the checks; it changes nothing.

### 7. Still left for later

From ADR-055's list: the side-by-side preview of the original, progress by Server-Sent Events (the batch list of §4 already shows which file is running), and work profiles (ADR-021, v0.3).

## Alternatives considered

| Alternative | Why not |
|---|---|
| Send several files in one request and let the server build the ZIP | One request could hold 50 × 200 MB; the server would hold every result in memory and the one-at-a-time rule would cover a whole batch. One request per file keeps every existing limit as it is. |
| Let the browser download each file separately | Browsers block or ask about many downloads from one page; one ZIP is one question. |
| Use a JavaScript ZIP library | ADR-055 keeps the page free of external code; an uncompressed ZIP is a small, well-documented format. |
| Multipart upload for verify | Needs a multipart parser: a new dependency, or Sugo's own parser of a format larger than the two lengths it needs. |
| Show the receipt only as a file to download | The point of the receipt is to see what was removed and why; the page is where that is easiest to read. |

## Consequences

- New public contract (principle 12): routes `/api/verify` and `/api/doctor`, headers `X-Sugo-Receipt`, `X-Sugo-Name`, `X-Sugo-Receipt-Length`, `X-Sugo-Cache`, and the `receipt` object in `/api/convert` responses. No new error code and no new CLI flag.
- No new dependency. The page's script grows (batch list, ZIP writer, receipt lists, verify form); new Italian texts for the page.
- THREAT_MODEL E gains: a receipt from an untrusted source is parsed by the strict model and its texts are shown as text; names inside the ZIP cannot hold paths. A security review is required before merging, as for ADR-055.
- ROADMAP v0.1 row for the web UI is updated: removal list and several files are no longer left for later.
- Suggested order of work, one pull request each: (1) receipt, edits count and file name; (2) no cache and installation check; (3) paste; (4) verify; (5) several files and ZIP.
