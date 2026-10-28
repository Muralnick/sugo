# Bundled tokenizer vocabularies

Sugo ships its tokenizer vocabularies so token counting works offline and never
reaches the internet (principle 1, ADR-036, ADR-038).

| File | Origin | SHA-256 | Licence |
|---|---|---|---|
| `o200k_base.tiktoken` | `https://openaipublic.blob.core.windows.net/encodings/o200k_base.tiktoken`, as referenced by tiktoken 0.14.0 | `446a9538cb6c348e3516120d7c08b09f57c36495e2acfffe59a5bf8b0cfb1a2d` | MIT, see `LICENSE-tiktoken` |

The hash is the one pinned in tiktoken's own source (`tiktoken_ext/openai_public.py`)
and is checked by `sugo.metrics.tokenizer` every time the file is loaded.
