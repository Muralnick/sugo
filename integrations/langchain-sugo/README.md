# langchain-sugo

A LangChain document loader for [Sugo](https://github.com/Muralnick/sugo). Sugo converts PDF, Word, Excel, PowerPoint, images and XML into compact Markdown on your own computer, and splits it into chunks along headings and pages.

> Not published yet: it needs the Python API that ships in `sugo-cli` 0.2.

```bash
pip install langchain-sugo
```

## Load documents

```python
from langchain_sugo import SugoLoader

documents = SugoLoader(["handbook.pdf", "prices.xlsx"]).load()
```

Each LangChain `Document` is one Sugo chunk. Its `id` is Sugo's chunk id, which stays the same when you load the same file again, so a vector store can update in place instead of storing duplicates:

```python
vector_store.add_documents(documents)  # ids come from Sugo
```

`mode="document"` gives one document per file, with the whole Markdown, for when you split text yourself.

## Metadata

Every value is a string, an integer or a boolean, so every vector store accepts it.

| Key | Value |
|---|---|
| `source` | The path as given |
| `document_id`, `chunk_id` | Sugo's ids (`chunk_id` in chunk mode only) |
| `page_start`, `page_end` | First and last page, counted from 1 |
| `heading_path` | Headings above the chunk, joined with ` > ` |
| `tokens` | Tokens of the text |
| `source_sha256`, `sugo_version`, `config_hash` | Where the text came from and what produced it |
| `partial` | True when some pages of the file could not be read |

## Options

| Option | Default | Meaning |
|---|---|---|
| `mode` | `"chunks"` | `"chunks"` or `"document"` |
| `max_tokens` | your Sugo chunk size | Chunk size in tokens |
| `on_error` | `"raise"` | `"skip"` leaves out files Sugo refuses and lists them in `loader.skipped` |
| `on_secret` | `"skip"` | Files with credentials (passwords, keys in XML): `"skip"`, `"include"` or `"raise"` |
| `cache` | `"ephemeral"` | `"user"` keeps Sugo's page cache, much faster when you reload files |

Files that hold credentials are skipped by default: a RAG pipeline usually sends text to an embedding service and stores it where other people and agents can read it. `loader.skipped` lists every file left out, with a code such as `CONTENT_EXCLUDED`.

## Privacy and network

The loader and Sugo open no network connection, and Sugo sends nothing anywhere. LangChain itself can: LangSmith tracing starts only if you set its environment variables. Once you have the documents, where your pipeline sends them (an embedding API, a database) is your choice.

Log messages never contain file names or document text.

## Licence

AGPL-3.0-or-later, like Sugo, which this loader runs. LangChain itself is MIT. This is not legal advice: if you build a service on it, read the licence. See the [licence decision record](https://github.com/Muralnick/sugo/blob/main/docs/adr/ADR-010-license.md).
