# llama-index-readers-sugo

A LlamaIndex reader for [Sugo](https://github.com/Muralnick/sugo). Sugo converts PDF, Word, Excel, PowerPoint, images and XML into compact Markdown on your own computer, and splits it into chunks along headings and pages.

It needs `sugo-cli` 0.2 or later, which `pip` installs with it.

```bash
pip install llama-index-readers-sugo
```

## Read documents

```python
from llama_index.readers.sugo import SugoReader

documents = SugoReader().load_data(["handbook.pdf", "prices.xlsx"])
```

Or let `SimpleDirectoryReader` walk a folder and hand Sugo the files it reads:

```python
from llama_index.core import SimpleDirectoryReader

sugo_reader = SugoReader()
reader = SimpleDirectoryReader(
    "documents/",
    file_extractor={
        suffix: sugo_reader for suffix in (".pdf", ".docx", ".xlsx", ".pptx", ".png", ".jpg")
    },
)
documents = reader.load_data()
```

Each document is one Sugo chunk, already split along headings and pages. Its `id_` is Sugo's chunk id, which stays the same when you load the same file again, so an index can update instead of storing duplicates. `SugoReader(mode="document")` gives one document per file, for when you split text yourself.

## Metadata

Every value Sugo adds is a string, an integer or a boolean.

| Key | Value |
|---|---|
| `source` | The path as given |
| `document_id`, `chunk_id` | Sugo's ids (`chunk_id` in chunk mode only) |
| `page_start`, `page_end` | First and last page, counted from 1 |
| `heading_path` | Headings above the chunk, joined with ` > ` |
| `tokens` | Tokens of the text |
| `source_sha256`, `sugo_version`, `config_hash` | Where the text came from and what produced it |
| `partial` | True when some pages of the file could not be read |

Ids, digests, versions and counts are excluded from the text sent to the embedding model and to the LLM, so they cost no tokens. Metadata passed by `SimpleDirectoryReader` (`file_name`, `file_path`, …) is kept; Sugo's keys win where names clash.

## Options

| Option | Default | Meaning |
|---|---|---|
| `mode` | `"chunks"` | `"chunks"` or `"document"` |
| `max_tokens` | your Sugo chunk size | Chunk size in tokens |
| `on_error` | `"raise"` | `"skip"` leaves out files Sugo refuses and lists them in `reader.skipped` |
| `on_secret` | `"skip"` | Files with credentials (passwords, keys in XML): `"skip"`, `"include"` or `"raise"` |
| `cache` | `"ephemeral"` | `"user"` keeps Sugo's page cache, much faster when you reload files |

Files that hold credentials are skipped by default: a RAG pipeline usually sends text to an embedding service and stores it where other people and agents can read it. `reader.skipped` lists every file left out, with a code such as `CONTENT_EXCLUDED`.

Sugo reads local files only: passing a remote `fs` raises an error.

## Privacy and network

The reader and Sugo open no network connection, and Sugo sends nothing anywhere. LlamaIndex itself can: for example its default LLM and embedding settings call online services, and some features download data. The tests of this package build an index with network access blocked. Once you have the documents, where your pipeline sends them is your choice.

Log messages never contain file names or document text. `SimpleDirectoryReader` prints the name of a file it fails to load; that message comes from LlamaIndex.

## Licence

AGPL-3.0-or-later, like Sugo, which this reader runs. LlamaIndex itself is MIT. This is not legal advice: if you build a service on it, read the licence. See the [licence decision record](https://github.com/Muralnick/sugo/blob/main/docs/adr/ADR-010-license.md).
