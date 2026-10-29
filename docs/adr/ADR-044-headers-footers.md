# ADR-044: Running headers, footers and page numbers

**Status:** Accepted  
**Date:** 2026-10-29  
**Deciders:** project author  
**Implements:** ADR-006 (pass 2, analysis), ADR-041 (cleaner decisions), ARCHITECTURE §4 (analyzer contract), THREAT_MODEL C (output poisoning)

## Context

Roadmap step 5b removes the page furniture that every PDF page repeats: a running title, "Confidential", a page number. In a chunked RAG index these lines are pure cost, and they split paragraphs that cross a page break. One page alone cannot tell a running header from a heading; only the whole document shows that a text repeats. The same repetition is an attack surface: a key clause printed at the bottom of every page could be removed as a footer (THREAT_MODEL C), or hidden copies of a clause could make its one visible copy look repeated.

## Decision

### Analyzer

`sugo.analyzers.edges.EdgeAnalyzer` implements the analyzer contract: `observe(page)` once per page, in any order, then `finalize()` returns frozen `EdgeStats`. The result does not depend on page order (principle 6), and observing a page index twice is refused.

- **Edge blocks:** text blocks (paragraph, heading, list item, header, footer, page number) whose box lies entirely in the top or bottom 10% of the page; at most 8 per band, nearest the edge first, so a hostile page cannot inflate memory. **Removed and flagged blocks are ignored** (hidden, illegible, low agreement, suspicious instruction): they neither count as a copy nor get removed as one.
- **Pattern:** the text after NFKC normalisation, case folding and whitespace collapsing, with digit runs masked (`Page 3 of 10` → `page # of #`). Only a 16-byte BLAKE2b digest of the pattern is kept, never the text (principle 11), so memory per page is constant.
- **Repeated:** a pattern in the same band on at least 3 pages, covering at least 40% of the pages between its first and last copy (a header on every other page qualifies; a heading recurring at the top of three distant pages does not). Each masked number must either never change ("2026") or always equal the page index plus a fixed offset ("3", "4", "5"); one disagreeing copy cancels the pattern. "Section 3", "Section 7" therefore never qualifies.
- **Page numbers:** a short text (≤ 30 characters) that is only a page number: arabic or strictly valid roman numerals, with optional dashes, brackets, a prefix (`page`, `p.`, `pagina`, `seite`, …) and a total (`of 90`, `di 90`, `/90`). A sequence is a (band, numeral system, number − page index) triple seen on pages meeting the same 3-page, 40% rules. Roman front matter and an arabic body form separate sequences. The same number on every page is not a sequence and stays.

### Cleaners

Both take `propose(page, stats)`, the full contract of ARCHITECTURE §4, and only propose removals (ADR-041).

- `PageNumberCleaner` (`page_numbers`) removes page numbers that belong to a sequence, reason `page number`.
- `HeaderFooterCleaner` (`headers_footers`) removes copies of repeated patterns, reason `running header|footer repeated on N pages`. It skips page-number texts, so the two cleaners never claim the same block.
- **Substantive text keeps its first copy** (maintainer decision): a pattern of 6 or more words may be a clause, not boilerplate. Its copy on the first page where it appears stays in the output; later identical copies are removed with the reason `…; first copy kept on page N`. Nothing substantive leaves the output, and a clause repeated on every page costs one copy instead of N.

Cleaning order for PDF pages: hidden text, page numbers, headers and footers. An import-linter contract keeps analyzers on the IR only (no extractors, cleaners, serializers, ports or network); serializers may not import analyzers.

## Alternatives considered

| Alternative | Why not |
|---|---|
| Never remove substantive repeated text | One clause repeated on 100 pages costs 100 times its tokens |
| Remove all copies and flag the removal | Content leaves the output; needs a new decision kind and report format |
| Keep the first copy of every repeated text | A chapter title repeated as a running header would reappear in the middle of the chapter's text |
| Match by position or font instead of text | Fragile across scanners and OCR; text with masked numbers is enough and cheap |
| Remove any lone number at a page edge | A "5" in a figure caption or table would go; the sequence check makes removal evidence-based |
| Store texts in the analyzer | Memory grows with the document, and content would sit in statistics that may later be cached |
| Harmonise heading levels across pages now | Cleaners can only remove blocks (ADR-041); changing a heading level needs a new decision kind. Deferred to the extension API |

## Consequences

- Documents shorter than 3 pages keep their headers, footers and page numbers: too little evidence.
- A running header whose number is misprinted on one page stays on every page, a few tokens lost for safety.
- On a synthetic 5-page report (running title, a 10-word clause in the footer, page numbers) cleaning cuts the text from 419 to 316 o200k_base tokens (−25%), keeping the clause once. The measurement is `test_pdf_report_loses_only_its_page_furniture`, which fails if the saving drops below 20%. Corpus numbers come with step 8.
- Residual risks: page furniture printed in the side margins or in the middle of the page stays; a header that changes wording on every page (e.g. the current section title) is removed only if it repeats on at least 3 nearby pages; heading levels still differ between pages (ADR-043).
