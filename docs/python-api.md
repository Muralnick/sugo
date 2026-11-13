# Python API

Sugo can be used from your own Python code. The public API is what the `sugo` package exports (ADR-067); everything else inside Sugo can change in any release. It is 0.x: the API may still change, with notice in the changelog, before 1.0.

```bash
pip install sugo-cli
```

## Convert a file

```python
import sugo

result = sugo.convert("reports/q3.pdf")
print(result.markdown)
print(result.tokens, "tokens,", result.pages, "pages")
```

`source` is the path to one file, or the file's bytes. Sugo reads PDF, DOCX, XLSX, PPTX, PNG, JPEG, WEBP and XML. Folders, wildcards and URLs are not accepted: Sugo never downloads anything.

```python
data = open("scan.png", "rb").read()
result = sugo.convert(data, name="inbox/scan.png")
```

`name` gives a document passed as bytes its identity: the same name keeps the same document and chunk ids across new editions of the file.

## Chunks for RAG

```python
result = sugo.convert("handbook.docx", chunks=True, max_tokens=400)
for chunk in result.chunks:
    print(chunk.id, chunk.pages, " > ".join(chunk.heading_path))
    print(chunk.text)
```

Each `sugo.Chunk` has the fields of the published JSON Schema (`schemas/chunk-v1.schema.json`): a stable `id`, `document_id`, `source`, `text`, `tokens`, `heading_path`, `pages`, `sugo_version` and `config_hash`. `max_tokens` defaults to your configured chunk size (512 unless changed).

## What the result holds

| Field | Meaning |
|---|---|
| `markdown` | The converted document |
| `chunks` | Chunks, only with `chunks=True` |
| `source`, `source_sha256`, `kind`, `pages` | What was converted |
| `document_id` | The document's stable id, the same one every chunk carries |
| `failed_pages`, `partial` | Pages that could not be read; `partial` is true if there are any |
| `removed`, `edited` | Blocks removed and texts edited, per cleaner, each with a reason in the receipt |
| `secret_blocks` | Blocks flagged as holding credentials, such as passwords in an XML file |
| `tokens` | Tokens of the Markdown (o200k_base) |
| `sugo_version`, `config_hash` | What produced the output, for reproducibility |
| `receipt` | The receipt as JSON, only with `receipt=True` (see `sugo verify`) |

Its fields cannot be reassigned, and `removed`, `edited` and `receipt` are read-only mappings.

## Errors

```python
try:
    result = sugo.convert("contract.pdf")
except sugo.SugoError as error:
    print(error.code, error.message, error.hint)
```

`SugoError.code` is the same stable code the CLI and the MCP server use, such as `PDF_ENCRYPTED` or `INPUT_UNSUPPORTED`. Match on the code: the message may be translated. A path that cannot be read raises `OSError`, and wrong arguments raise `ValueError` or `TypeError`.

## Settings and cache

- `convert` uses the same settings as the `sugo` command: your user configuration file, a `sugo.toml` in the current folder, and `SUGO_*` environment variables. Arguments override them.
- By default each call uses a temporary page cache that is deleted when the call ends, so no document text stays on disk. Pass `cache="user"` to use your persistent page cache instead, like the CLI: loading the same files again is then much faster. `sugo cache clear` deletes it.

## Good to know

- `import sugo` is fast: the conversion engine loads on the first call.
- Sugo prints nothing and adds no logging handler. Its log messages, under the `sugo` logger, never contain document text or file names.
- Run one conversion at a time per process in this version. Several processes are fine.
- Everything runs on your machine: Sugo sends nothing anywhere. Where your own code sends the result afterwards is up to you.
