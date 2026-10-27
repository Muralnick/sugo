# Sugo

**Documents, reduced.** Feed your LLM the sauce, not the water.

Sugo converts PDFs, screenshots, images, Office files, e-books, emails and web pages into clean, compact Markdown for RAG systems, AI agents and LLM chats. It strips the noise (headers, footers, page numbers, disclaimers, UI chrome, decorative images) so you send fewer tokens without losing meaning, tables or structure. Everything runs locally on your machine.

> In Italian, *il sugo del discorso* means "the gist", and a *sugo* is a sauce you **reduce** until only the concentrated flavour remains. That is what Sugo does to your documents.

## Status

**Architecture phase completed (October 2026). Implementation not started.** The full design lives in [`docs/`](docs/). Start from [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Highlights (planned)

- **Screenshot-first**: chats, code, UI screenshots and phone photos become clean text, with dark-mode handling and scrolling-screenshot deduplication.
- **Honest token metrics**: savings measured per pipeline stage and compared with what each provider (Claude, Gemini, OpenAI) would charge for the original image, including the cases where sending the image is cheaper.
- **Three engine levels**: `lite` (any 8 GB laptop), `normal` (complex tables, Office), `quality` (GPU, local vision-language model).
- **Eight languages**: Italian, Spanish, English, French, German, Japanese, Mandarin Chinese, Korean.
- **For developers and agents**: Claude Code-style shell, MCP server for Claude Code, Codex and other agents, `--json` everywhere.
- **For companies and law firms**: offline mode, anonymization of personal data, audit log, reproducible output.
- **Local by principle**: no cloud APIs, no telemetry, ever.

## Documentation

| Document | Content |
|---|---|
| [ARCHITECTURE](docs/ARCHITECTURE.md) | Complete system design |
| [FEATURES](docs/FEATURES.md) | Features by engine level, work profiles, supported formats |
| [THREAT_MODEL](docs/THREAT_MODEL.md) | Security analysis |
| [TESTING](docs/TESTING.md) | Testing, benchmarks, performance targets |
| [ROADMAP](docs/ROADMAP.md) | Development plan and first release scope |
| [ADRs](docs/adr/) | Architecture decision records |
| [PRINCIPLES](PRINCIPLES.md) | The promises Sugo never breaks |
| [AI_WORKFLOW](AI_WORKFLOW.md) | How this project is built with AI assistance |

## License

AGPL-3.0 (see [ADR-010](docs/adr/ADR-010-license.md)).

🇮🇹 [Leggi in italiano](README.it.md)
