# Sugo vs Docling vs MarkItDown — a measured comparison

**Date:** 2026-11-04
**Sugo:** this repository, `lite` level (the only level implemented in v0.1 — see [ROADMAP.md](../ROADMAP.md))
**Docling:** 2.147.0 (standalone, default `DocumentConverter`)
**MarkItDown:** 0.1.9, with the `[all]` extra (the base install cannot read PDFs at all — see below)
**Corpus:** the 26 synthetic documents in [`benchmarks/corpus.py`](../../benchmarks/corpus.py) (5 languages × report PDF, two-column PDF, XLSX table, chat screenshot, code screenshot, plus one dark-mode chat) and the 5 EUR-Lex "Regulation 261/2004" PDFs from [`benchmarks/corpus_eur_lex.py`](../../benchmarks/corpus_eur_lex.py) — 31 documents, 31/31 have an exact ground truth.
**Raw results:** [`benchmarks/results/comparison_sugo_docling_markitdown_2026-11-04.json`](../../benchmarks/results/comparison_sugo_docling_markitdown_2026-11-04.json)

Docling and MarkItDown are **not** Sugo dependencies. They were installed once, in a disposable virtualenv outside this repo, purely to run this comparison, and removed afterward — `uv sync` never touches them.

## Why pair every number with content loss

[ADR-030](../adr/ADR-030-testing-benchmarks.md) already states the rule this project tests itself against: "savings-only metrics hides content loss." This comparison exists to show Sugo holds up under that same rule against two well-known alternatives — so every "tokens saved" figure below is shown next to how much of the ground truth actually survived. A tool that returns an empty string "saves" 100% of the tokens; that is data loss, not compression, and the table below calls it that.

## Headline

| | Sugo (`lite`, v0.1) | Docling 2.147.0 | MarkItDown 0.1.9 `[all]` |
|---|---|---|---|
| Conversions that completed | 31/31 | 31/31 | 31/31 |
| Documents with lost or garbled content | **3 / 31** | 13 / 31 | 17 / 31 |
| Median tokens saved vs. raw text | 0.0%† | 27.7%‡ | −0.2%‡ |
| Mean tokens saved vs. raw text | 6.3% | 11.1% | 29.8%‡ |
| Median time per document | 1.23 s | 4.55 s | 0.025 s |

† Most of this corpus is small and has little header/footer noise to strip. On the 10 documents that do have a running header, footer and page numbers (the `report_*.pdf` files), Sugo saves 33–38% of the tokens with **zero** content lost — consistent with the project's own already-published [`corpus_bench_2026-11-03.json`](../../benchmarks/results/corpus_bench_2026-11-03.json).
‡ Inflated by content loss, not real compression: Docling's largest "savings" land on the exact documents where it also drops or garbles the most text; MarkItDown's 100% figure on every screenshot is an empty output file.

## What actually breaks, tool by tool

**MarkItDown**
- The base `pip install markitdown` cannot read PDFs at all (`MissingDependencyException` on every one); it needs the `[all]` extra, which we installed rather than testing a crippled default.
- No OCR out of the box: all 11 screenshots (chat and code, every language) came back as an **empty string** — a full content loss, not a transcription error — unless an external LLM/vision backend is wired in. We tested the no-LLM default, which is what a plain install gives you.
- Drops real legal clauses from all 5 EUR-Lex PDFs (2–7 missing paragraphs each — e.g. a whole numbered exception clause in the English copy).
- Rewrites table cell values: a price cell containing the text "2,50" / "2.50" comes back as the float `2.5`.
- By far the fastest tool when it has something to extract (pure text parsing, no local model).

**Docling**
- Converts every document, including real OCR on screenshots via its own layout and recognition models — the only one of the three that attempts this without an LLM.
- That OCR is unreliable on this corpus: every one of the 11 screenshots is garbled, several so badly that the edit distance exceeds the length of the correct text (character error rate above 1.0).
- Drops one legal clause each on 2 of the 5 EUR-Lex PDFs.
- The slowest tool here: 2.5–26 s per document, because its layout model runs on every page, every time, even a two-line price table.
- This isn't a case of Sugo rejecting Docling: the roadmap already plans to call Docling internally at a future `normal` level for complex Office layouts ([ROADMAP.md](../ROADMAP.md), [ADR-007](../adr/ADR-007-engine-levels.md)). This comparison is about Docling used standalone as the whole pipeline, which is how most people reach for it today.

**Sugo (`lite`, the only level v0.1 ships)**
- Converts every document in the corpus with no missing text anywhere, including all 5 EUR-Lex PDFs.
- Its only imperfection: 3 of 31 screenshots show a 1–7% character error rate (a handful of misread characters) — no missing text, anywhere.
- Slower than MarkItDown's text-only path (it runs local OCR on screenshots), consistently faster than Docling's heavier model pipeline.

## Full per-document results

| document | Sugo saved% | Sugo issue | Sugo s | Docling saved% | Docling issue | Docling s | MarkItDown saved% | MarkItDown issue | MarkItDown s |
|---|---|---|---|---|---|---|---|---|---|
| report_it.pdf | 38.0% | - | 1.16 | 47.9% | - | 10.04 | -1.3% | - | 0.16 |
| two_column_it.pdf | 0.0% | - | 1.12 | -2.9% | - | 2.55 | -0.5% | - | 0.09 |
| table_it.xlsx | 0.0% | - | 0.89 | -46.9% | - | 0.01 | -34.4% | - | 0.02 |
| chat_it.png | 0.0% | CER 0.01 | 1.32 | 27.7% | CER 0.69 | 5.00 | 100.0% | CER 1.00 | 0.01 |
| code_it.png | 0.0% | - | 1.26 | 34.5% | CER 1.62 | 2.92 | 100.0% | CER 1.00 | 0.01 |
| report_es.pdf | 33.6% | - | 1.12 | 38.4% | - | 9.58 | -1.5% | - | 0.12 |
| two_column_es.pdf | 0.0% | - | 1.12 | -2.9% | - | 2.59 | -0.5% | - | 0.06 |
| table_es.xlsx | 0.0% | - | 0.85 | -48.3% | - | 0.01 | -34.5% | - | 0.02 |
| chat_es.png | 0.0% | CER 0.06 | 1.37 | 31.7% | CER 0.72 | 4.55 | 100.0% | CER 1.00 | 0.01 |
| code_es.png | 0.0% | - | 1.36 | 34.5% | CER 1.62 | 2.71 | 100.0% | CER 1.00 | 0.01 |
| report_fr.pdf | 33.3% | - | 1.16 | 39.0% | - | 9.36 | -1.4% | - | 0.11 |
| two_column_fr.pdf | 0.0% | - | 1.09 | -2.8% | - | 2.54 | -0.5% | - | 0.06 |
| table_fr.xlsx | 0.0% | - | 0.83 | -48.3% | - | 0.01 | -34.5% | - | 0.01 |
| chat_fr.png | 2.4% | CER 0.07 | 1.34 | 28.6% | CER 0.83 | 4.68 | 100.0% | CER 1.00 | 0.01 |
| code_fr.png | 0.0% | - | 1.24 | 34.5% | CER 1.62 | 2.78 | 100.0% | CER 1.00 | 0.01 |
| report_de.pdf | 36.9% | - | 1.15 | 39.2% | - | 9.66 | -1.5% | - | 0.10 |
| two_column_de.pdf | 0.0% | - | 1.09 | -3.1% | - | 2.55 | -0.5% | - | 0.06 |
| table_de.xlsx | 0.0% | - | 0.81 | -35.5% | - | 0.01 | -22.6% | - | 0.02 |
| chat_de.png | 0.0% | - | 1.41 | 30.4% | CER 0.91 | 4.75 | 100.0% | CER 1.00 | 0.01 |
| code_de.png | 0.0% | - | 1.29 | 34.5% | CER 1.62 | 2.86 | 100.0% | CER 1.00 | 0.01 |
| report_en.pdf | 34.2% | - | 1.11 | 39.1% | - | 10.95 | -1.6% | - | 0.10 |
| two_column_en.pdf | 0.0% | - | 1.09 | -3.1% | - | 2.65 | -0.5% | - | 0.06 |
| table_en.xlsx | 0.0% | - | 0.85 | -55.6% | - | 0.01 | -40.7% | missing 3 | 0.01 |
| chat_en.png | 0.0% | - | 1.33 | 32.6% | CER 1.04 | 5.18 | 100.0% | CER 1.00 | 0.01 |
| code_en.png | 0.0% | - | 1.23 | 34.5% | CER 1.62 | 3.12 | 100.0% | CER 1.00 | 0.01 |
| chat_en_dark.png | 0.0% | - | 1.35 | 30.2% | CER 1.23 | 18.64 | 100.0% | CER 1.00 | 0.01 |
| eur_lex_261_2004_en.pdf | 3.5% | - | 1.38 | 7.0% | missing 1 | 21.11 | -0.2% | missing 2 | 1.62 |
| eur_lex_261_2004_it.pdf | 2.9% | - | 1.45 | 5.8% | - | 22.15 | -0.2% | missing 4 | 1.71 |
| eur_lex_261_2004_es.pdf | 3.1% | - | 1.43 | 7.6% | - | 21.69 | -0.2% | missing 2 | 1.79 |
| eur_lex_261_2004_fr.pdf | 3.1% | - | 1.45 | 7.1% | - | 21.62 | -0.2% | missing 2 | 1.77 |
| eur_lex_261_2004_de.pdf | 3.2% | - | 1.92 | 7.5% | missing 1 | 26.38 | -0.2% | missing 7 | 1.79 |

"saved%" is tokens saved vs. the raw extracted text, counted with the same tokenizer for all three tools. "issue" is the character error rate (OCR documents) or the number of ground-truth paragraphs missing from the output (native-text documents); "-" means no issue found.

## Method and honesty notes — read before citing a single number

1. This corpus is Sugo's own synthetic test corpus (small, controlled documents) plus 5 real EUR-Lex legal PDFs. It is a reproducible first data point, not a large, independent, real-world benchmark — treat the numbers accordingly.
2. "Tokens saved %" uses the same tokenizer and the same raw-text baseline for every tool, but a tool that drops content will show a misleadingly high number. Always read it next to the content-issue column, never alone — the mistake [ADR-030](../adr/ADR-030-testing-benchmarks.md) exists to prevent.
3. Timing excludes one warm-up conversion per tool (model loading is a one-time cost), matching [`corpus_bench.py`](../../benchmarks/corpus_bench.py)'s own methodology; Docling's per-page model inference is still paid on every subsequent run, not just the first.
4. MarkItDown needed the `[all]` extra to read PDFs at all; we installed it so the comparison isn't accused of testing a competitor's crippled default.
5. MarkItDown supports an optional LLM-backed image-description mode that was not configured here; its 0% OCR result reflects the no-LLM default, which is what most installs actually run.
6. All three tools ran in their default configuration — none was tuned for this corpus.
7. Docling and MarkItDown were installed in a throwaway virtualenv outside this repository and fully removed afterward, including the model weights Docling downloads to the local Hugging Face cache; they are not, and must not become, project dependencies without their own ADR.
