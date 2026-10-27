# ADR-010: Licence: AGPL-3.0-or-later

**Status:** Accepted  
**Date:** 2026-10-27  
**Deciders:** project author  
**Amended:** 2026-10-27, "or later" variant chosen (was unspecified)

## Context

Sugo is published as open source on GitHub. PyMuPDF is AGPL; other main dependencies are Apache-2.0 or MIT; PyMuPDF's Office extension is commercial.

## Decision

Project licence **AGPL-3.0-or-later** (SPDX `AGPL-3.0-or-later`): later versions published by the FSF may be applied, so the project can follow licence updates without contacting every contributor. Office handled by Docling and lightweight libraries, never by PyMuPDF's commercial extension.

## Alternatives considered

| Alternative | Why not |
|---|---|
| MIT or Apache-2.0 | Incompatible with PyMuPDF without a commercial licence |
| Replace PyMuPDF | Loses speed and quality on native PDFs |

## Consequences

- Network-service integrators must publish their source.
- Final licence compatibility check before the first release.
