# ADR-001: Hybrid per-page routing across PyMuPDF, Docling and VLM

**Status:** Accepted  
**Date:** 2026-10-27  
**Deciders:** project author

## Context

Real documents mix easy pages (native text) and hard ones (complex tables, scans, diagrams). Docling and VLMs are accurate but slow on CPU; PyMuPDF is very fast but limited on complex layouts and scans. PyMuPDF's own benchmark shows very low OCR accuracy on documents over 50 pages, confirming long documents need differentiated handling.

## Decision

A router chooses the backend **per page**: PyMuPDF for native-text pages with simple layout; Docling for complex tables, Office and scans (`normal`); a VLM for the hardest pages (`quality`).

## Alternatives considered

| Alternative | Why not |
|---|---|
| PyMuPDF only | Fast but insufficient on scans and complex tables |
| Docling only | Accurate but too slow and heavy for long documents on modest machines |
| Per-document routing | A book with a few hard pages would be processed entirely by the slow backend |

## Consequences

- Books with few complex pages remain feasible on 8 GB machines.
- Requires a page-complexity classifier with thresholds calibrated by benchmarks.
- PyMuPDF is AGPL (ADR-010).
