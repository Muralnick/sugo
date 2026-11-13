# ADR-068: LangChain and LlamaIndex loaders

**Status:** Accepted (maintainer decisions of 2026-11-13: separate packages, AGPL; ADR approved the same day)
**Date:** 2026-11-13
**Deciders:** project author
**Implements:** ROADMAP v0.2 "LangChain and LlamaIndex loaders (needs an ADR: package layout, dependencies, licence questions for users)"
**Builds on:** ADR-010 (licence), ADR-023 (output schema), ADR-033 (release pipeline), ADR-035 (dependencies), ADR-053 (secret exclusions), ADR-067 (Python API)
**Amends:** ADR-033 (the pipeline publishes two more distributions)
**Adds:** two distributions, `langchain-sugo` and `llama-index-readers-sugo`
**Adds dependencies:** `langchain-core` and `llama-index-core`, only in those two distributions; none in `sugo-cli`

## Context

Most people who build RAG in Python load documents through LangChain or LlamaIndex. Both frameworks expect a loader class: LangChain's `BaseLoader` returns `Document` objects, and LlamaIndex's `BaseReader` returns its own `Document`. Today a Sugo user has to write that glue code themselves.

Facts checked on 2026-11-13:

| Package | Licence | Newest version at least 14 days old | Notable dependencies |
|---|---|---|---|
| `langchain-core` | MIT | 1.7.3 (2026-10-29) | httpx, langsmith (tracing, off unless configured), pydantic, pyyaml, tenacity |
| `llama-index-core` | MIT | 0.14.25 (2026-09-21) | aiohttp, httpx, nltk, networkx, fsspec |

Both bring network libraries and many packages that Sugo itself does not need. The names `langchain-sugo` and `llama-index-readers-sugo` are free on PyPI: both the JSON API and the simple index answer 404.

## Decision

### 1. Two separate distributions in this repository (maintainer decision)

```
integrations/
  langchain-sugo/              module langchain_sugo, class SugoLoader
  llama-index-readers-sugo/    module llama_index.readers.sugo, class SugoReader
```

- The names follow each ecosystem's convention, so users find them where they look (LangChain integrations, LlamaHub).
- Each package has its own `pyproject.toml` and its own `uv.lock` with hashes. `sugo-cli`'s lock, its install and its attack surface do not change: someone who installs only Sugo gets neither framework.
- Each package depends on `sugo-cli` within one minor series (e.g. `sugo-cli>=0.2,<0.3`) and on its framework within one major series (`langchain-core>=1.7,<2`, `llama-index-core>=0.14,<0.15`).
- They import only the public `sugo` names of ADR-067, enforced by an import-linter contract in each package.

### 2. Licence: AGPL-3.0-or-later, like Sugo (maintainer decision)

The licence decision for Sugo is still open. Keeping the loaders under the same licence makes no new commitment: they can move to a more permissive licence later, but code published under MIT stays MIT. Each package's README states plainly, without giving legal advice, that the loader runs Sugo, which is AGPL, and links the licence. It also says that the frameworks themselves are MIT.

### 3. What the loaders return

Both loaders take a single file path or a list of paths, call `sugo.convert` once per file, and offer two modes:

- `mode="chunks"` (the default): one framework document per Sugo chunk. Sugo's chunks follow headings and pages, which is the point of using Sugo. The chunk id (ADR-023) becomes the document id, so loading the same file again gives the same ids, and vector stores can update in place.
- `mode="document"`: one framework document per file, holding the whole Markdown, for users who split text themselves.

Metadata uses only strings, integers and booleans, since several vector stores reject lists:

| Key | Value |
|---|---|
| `source` | The path as given |
| `document_id`, `chunk_id` | Sugo's ids (`chunk_id` only in chunk mode) |
| `page_start`, `page_end` | First and last page, counted from 1 |
| `heading_path` | The headings above the chunk, joined with ` > ` |
| `tokens` | Tokens of the text (o200k_base) |
| `source_sha256`, `sugo_version`, `config_hash` | Provenance and reproducibility (principles 5 and 6) |
| `partial` | True when some pages of the file could not be read |

In LlamaIndex, the ids and digests are excluded from the embedding and LLM text (`excluded_embed_metadata_keys`, `excluded_llm_metadata_keys`), so they cost no tokens. `SugoReader` also works as a `file_extractor` in `SimpleDirectoryReader`.

Folders and archives are not handled by the loaders: the frameworks' own directory loaders already walk folders. Sugo's own containers come in v0.4.

### 4. Failures and documents with credentials

- A file Sugo refuses raises `SugoError` (`on_error="raise"`, the default), so nothing goes missing without the user noticing. `on_error="skip"` skips it and counts it in the loader's `skipped` attribute, with the error code.
- A document flagged as holding credentials (`secret_blocks > 0`, ADR-053) is **skipped by default** (`on_secret="skip"`) and counted in `skipped`. A RAG pipeline usually sends text on to an embedding service and stores it in a database shared with other people and agents: that is the MCP server's situation, not a user reading the file. `on_secret="include"` loads it anyway (the credential blocks are already removed from the Markdown), and `on_secret="raise"` stops.
- Warnings use the `sugo` logger and never include file names or text at the default level (principle 11). The `skipped` list holds the paths, for the caller's own code.

### 5. Network and telemetry

The loaders open no connection. The frameworks may: LangSmith tracing turns on only when the user sets its environment variables, and some framework features download data such as NLTK files. The packages' READMEs say this, and their tests run with network access blocked, so a loader that triggers a download fails the tests. Sugo's principles 1 and 2 cover Sugo's own code: once the loader returns the documents, where the user's pipeline sends them is the user's choice, and the README says so.

### 6. Tests and CI

- Unit tests with the framework installed, on the synthetic corpus: ids are stable between two loads, metadata types are accepted by the in-memory vector stores of both frameworks, the default secret handling and the error options behave as described.
- A CI job per package: `ruff`, `mypy`, `import-linter`, tests, `uv lock --check`. The jobs run when `integrations/` or `src/sugo/` changes.

### 7. Release (amends ADR-033)

- Each package has its own version and its own tag prefix: `langchain-sugo-v0.1.0`, `llama-index-readers-sugo-v0.1.0`. The release workflow builds, attests and publishes the package that matches the tag, with the same steps as `sugo-cli`: two builds compared for reproducibility, SBOM, Sigstore attestation, PyPI Trusted Publishing.
- The maintainer creates both projects on PyPI and adds this repository as a trusted publisher once, by hand, as for `sugo-cli`.
- Listing on LlamaHub and in the LangChain integration docs comes after the first release, with texts written by the maintainer.

## Alternatives considered

- **Extras of `sugo-cli` (`sugo-cli[langchain]`).** One release instead of three, but `sugo-cli`'s lock and dev environment would carry both frameworks and their network libraries. Rejected (maintainer decision).
- **Only examples in the README.** No dependency at all, but not listed on LlamaHub and easy to copy wrongly (ids, metadata types). It can still go in the docs as the way to see what the loaders do.
- **MIT licence for the loaders.** Friendlier for the frameworks' communities, but a commitment that cannot be taken back while Sugo's own licence is undecided. Rejected for now (maintainer decision); it can be reconsidered after that decision.
- **Contributing the loaders upstream (`langchain-community`, the LlamaIndex repository).** Their maintainers would control releases, and `langchain-community` is no longer where new integrations go. Rejected.

## Consequences

- Three distributions to release and keep in step. The tag prefixes keep each release separate.
- The loaders depend on ADR-067, which must ship first, in `sugo-cli` 0.2.
- Two framework dependencies enter the repository, each in its own lock, and their updates follow the 14-day rule like every other dependency.
