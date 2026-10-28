# ADR-042: Markdown output format

**Status:** Accepted  
**Date:** 2026-10-28  
**Deciders:** project author  
**Implements:** ADR-002 (adaptive tables), ADR-026 (`[illegible]` marker), ARCHITECTURE §4 (serializer contract)

## Context

Roadmap step 4 renders IR blocks as the Markdown Sugo hands to LLMs. This text is a public contract: RAG pipelines and prompts depend on its shape. It must cost as few tokens as possible, lose nothing that was not removed with a reason (principle 3), invent nothing (principle 4), and must not let document text pose as structure, such as a fake heading, a fake chat speaker or a fake `[illegible]` marker.

## Decision

`sugo.serializers.markdown.render(blocks)` renders blocks in the order given (their reading order), without a trailing newline.

| Block | Output |
|---|---|
| Removed | Nothing; it stays in the IR with its reason |
| Illegible (any type) | `[illegible]`, with the list or speaker prefix of its type |
| Heading | `#` × level (1 when unknown), lines joined with a space |
| List item | `- text` |
| Chat message | `left: text` or `right: text`, the neutral side (ADR-040); without a side, plain text |
| Code | Fenced block, text unchanged; the fence is longer than any backtick run inside |
| Table | Cheapest faithful format, below |
| Any other type, not removed | Its text; only cleaners decide what is dropped |
| Empty or whitespace-only text | Nothing |

- Blocks are separated by a blank line; consecutive list items and consecutive chat messages by one newline. Further lines of a list item or chat message are indented by two spaces, so a line reading `right: I agree` inside a left bubble cannot pass for a new message.
- **Minimal escaping:** a backslash is added only where text would open structure: at the start of a line (`# > | : = + * - _` backticks, tildes, `1.` and `1)`), before a closing `#` sequence of a heading, and before `[illegible]` written in the document. Ordinary text gets no extra tokens. Raw HTML is not escaped: the output is read by LLMs, and a port that renders it for people must sanitise it.
- **Tables:** two candidates, measured with o200k_base; the cheaper one wins and ties go to the first.
  1. *Compact table:* `Name|Age` / `-|-` / `Anna|30`, no padding and no outer pipes. Outer pipes are added when a row starts or ends with an empty cell, which would otherwise be lost, and for one-column tables. Tables without header rows have no delimiter row. `|` inside a cell becomes `\|`.
  2. *Row sentences:* `Name: Anna; City: Rome` per row, empty cells omitted. Only when the table has a header with unique, non-empty labels, and no label or cell contains characters that would make it ambiguous (`:` in labels, `;` anywhere). A row with no values makes this format unavailable.
  Spanning cells repeat their text in every cell they cover; several header rows merge per column as `Top / Sub`; line breaks inside a cell become `<br>`.
- An import-linter contract keeps serializers away from extractors, cleaners, ports and the network gateway and its users.

### Measured

| Sample | Standard padded Markdown table | Sugo | Change |
|---|---|---|---|
| Invoice, 5 columns × 10 rows | 314 tokens | 221 (compact) | −30% |
| Contact list, 6 columns × 4 rows, mostly empty | 101 tokens | 53 (row sentences) | −48% |

Corpus numbers come with step 8.

## Alternatives considered

| Alternative | Why not |
|---|---|
| `key: value` for two-column tables without header (approved first, then measured) | One or two tokens more than the compact table on every sample; it would never be chosen |
| Speaker as `L:`/`R:`, `[left]`, or bold `**left:**` | Same cost or more, and less clear; bold costs two tokens per message |
| No escaping | Cheapest, but OCR text such as `# 1 in classifica` becomes a heading, and hostile text can fake structure |
| Full CommonMark escaping | Many extra tokens on technical text and identifiers (`file\_name`) |
| Standard padded tables | 30–50% more tokens on the samples |

## Consequences

- Consumers must handle two table representations; both are documented here and will be listed in the user documentation with the exporters (step 6).
- A paragraph whose first line starts with four or more spaces renders as an indented code block; its text is unchanged.
- Line recomposition (joining OCR lines, hyphens) is left to the language packs; until then, paragraph lines are kept as extracted.
