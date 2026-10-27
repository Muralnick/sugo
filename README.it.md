# Sugo

**Documenti, ridotti.** Dai al tuo LLM il sugo, non l'acqua.

Sugo converte PDF, screenshot, immagini, file Office, e-book, email e pagine web in Markdown pulito e compatto, pensato per sistemi RAG, agenti AI e chat con gli LLM. Elimina il rumore (intestazioni, piè di pagina, numeri di pagina, disclaimer, elementi d'interfaccia, immagini decorative) per inviare meno token senza perdere significato, tabelle o struttura. Tutto gira in locale, sul tuo computer.

> "Il sugo del discorso" è il succo, l'essenza; e il sugo, in cucina, si **riduce** finché resta solo il sapore concentrato. È quello che Sugo fa con i tuoi documenti.

## Stato

**Fase di architettura completata (ottobre 2026). Implementazione non ancora iniziata.** Il progetto completo è nella cartella [`docs/`](docs/) (in inglese). Il punto di partenza è [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Caratteristiche principali (previste)

- **Screenshot al centro**: chat, codice, schermate e foto dal telefono diventano testo pulito, con gestione della dark mode ed eliminazione dei duplicati negli screenshot di scorrimento.
- **Metriche oneste**: risparmio misurato per ogni fase e confrontato con il costo che ogni provider (Claude, Gemini, OpenAI) applicherebbe all'immagine originale, inclusi i casi in cui inviare l'immagine conviene.
- **Tre livelli di motore**: `lite` (qualsiasi portatile da 8 GB), `normal` (tabelle complesse, Office), `quality` (GPU, modello visivo locale).
- **Otto lingue**: italiano, spagnolo, inglese, francese, tedesco, giapponese, cinese mandarino, coreano.
- **Per sviluppatori e agenti**: shell in stile Claude Code, server MCP per Claude Code, Codex e altri agenti, output `--json` ovunque.
- **Per aziende e studi legali**: modalità offline, anonimizzazione dei dati personali, registro delle operazioni, output riproducibile.
- **Supporto dedicato all'Italia**: PEC, fattura elettronica, codice fiscale e partita IVA, ricette per documenti legali italiani.
- **Locale per principio**: nessuna API cloud, nessuna telemetria, mai.

## Licenza

AGPL-3.0-or-later (vedi [ADR-010](docs/adr/ADR-010-license.md)).

🇬🇧 [Read in English](README.md)
