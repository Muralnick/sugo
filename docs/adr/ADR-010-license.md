# ADR-010: Licence: AGPL-3.0

**Status:** Accepted  
**Date:** 2026-10-27  
**Deciders:** project author

## Context

Sugo is published as open source on GitHub. PyMuPDF is AGPL; other main dependencies are Apache-2.0 or MIT; PyMuPDF's Office extension is commercial.

## Decision

Project licence **AGPL-3.0**. Office handled by Docling and lightweight libraries, never by PyMuPDF's commercial extension.

## Alternatives considered

| Alternative | Why not |
|---|---|
| MIT or Apache-2.0 | Incompatible with PyMuPDF without a commercial licence |
| Replace PyMuPDF | Loses speed and quality on native PDFs |

## Consequences

- Network-service integrators must publish their source.
- Final licence compatibility check before the first release.
