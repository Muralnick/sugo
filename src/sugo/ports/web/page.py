"""The page, its style and script, shipped inside the package (ADR-055).

Nothing is loaded from the internet: no CDN, font or analytics, so the page
works offline and sends nothing out. Its text is Sugo's own, in every
interface language, handed to the script as one JSON value in a ``<meta>``
attribute together with the user's settings; the script inserts every text
with ``textContent`` and switches language without asking the server.
"""

import html
import json
from functools import cache
from importlib import resources
from string import Template
from typing import Any

from sugo import i18n
from sugo.config.settings import Settings
from sugo.core.constants import (
    CHUNK_MAX_TOKENS_LIMIT,
    CHUNK_MIN_TOKENS,
    MAX_IMAGE_FILE_BYTES,
    MAX_INPUT_BYTES,
    MAX_OFFICE_FILE_BYTES,
    MAX_PDF_FILE_BYTES,
    MAX_XML_FILE_BYTES,
)
from sugo.i18n import N_
from sugo.languages.packs import PACKS

_MB = 1024 * 1024
_LARGE_MB = max(MAX_PDF_FILE_BYTES, MAX_OFFICE_FILE_BYTES) // _MB
_SMALL_MB = max(MAX_IMAGE_FILE_BYTES, MAX_XML_FILE_BYTES) // _MB

# Files served as they are, by URL path: (file name, media type).
STATIC = {
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/app.css": ("app.css", "text/css; charset=utf-8"),
}

# Text the script fills its placeholders into: {before}, {after}, {saved},
# {pages}, {count}, {provider}, {hint}, {tokens} and {number}. {large},
# {small}, {size}, {min} and {max} are filled here.
_TEXTS = {
    "tagline": N_("Documents, reduced: drop a file to get its compact Markdown."),
    "tab_convert": N_("Convert"),
    "tab_settings": N_("Settings"),
    "tab_questions": N_("Questions"),
    "drop": N_("Drop a file here"),
    "choose": N_("Choose a file"),
    "formats": N_(
        "PDF, DOCX, XLSX or PPTX up to {large} MB; PNG, JPEG, WEBP or XML up to {small} MB."
    ),
    "too_large": N_("This file is larger than {size} MB."),
    "empty": N_("This file is empty."),
    "converting": N_("Converting…"),
    "markdown": N_("Markdown"),
    "copy": N_("Copy"),
    "copied": N_("Copied"),
    "copy_failed": N_("The browser did not allow copying; select the text and copy it."),
    "save": N_("Save as .md"),
    "tokens_before": N_("Tokens before"),
    "tokens_after": N_("Tokens after"),
    "tokens_saved": N_("Saved"),
    "pages_label": N_("Pages"),
    "text_savings": N_(
        "Text before and after cleaning: {before} -> {after} tokens ({saved}% saved)"
    ),
    "images_title": N_("Sending the image vs sending its Markdown"),
    "provider": N_("provider"),
    "tier": N_("tier"),
    "image_tokens": N_("image tokens"),
    "markdown_tokens": N_("Markdown tokens"),
    "saved": N_("saved"),
    "rejected": N_("rejected"),
    "unverified": N_("{provider} (unverified)"),
    "failed_pages": N_("Pages that could not be read: {pages}"),
    "removed_title": N_("Blocks removed, per cleaner"),
    "removed_none": N_("No blocks removed."),
    "chunks_title": N_("Chunks"),
    "chunks_count": N_("{count} chunks (chosen size: {tokens} tokens)"),
    "chunk_label": N_("Chunk {number} · {tokens} tokens"),
    "chunk_pages": N_("pages {pages}"),
    "save_jsonl": N_("Save as .jsonl"),
    "error": N_("error"),
    "hint": N_("hint: {hint}"),
    "unexpected": N_("Something went wrong; the terminal running sugo ui may say more."),
    "no_token": N_("Open the address sugo ui printed in the terminal."),
    "local_only": N_("Sugo runs on this computer only. To stop it, press Ctrl+C in the terminal."),
    # Settings
    "settings_intro": N_(
        "These choices apply to the next conversion. This browser remembers them; "
        "your configuration file is not changed."
    ),
    "ui_language": N_("Interface language"),
    "text_languages": N_("Languages of your documents"),
    "text_languages_help": N_("Sugo applies their text rules when cleaning. Choose at least one."),
    "strip_tracking": N_("Remove tracking parameters from links (utm_source and similar)"),
    "make_chunks": N_("Also split into chunks for RAG"),
    "chunk_size": N_("Chunk size in tokens ({min} to {max})"),
    "reset": N_("Back to my configuration"),
    "lang_en": N_("English"),
    "lang_it": N_("Italian"),
    "lang_es": N_("Spanish"),
    "lang_fr": N_("French"),
    "lang_de": N_("German"),
}

# The Questions page: (question, answer) pairs.
_QUESTIONS = (
    (
        N_("What does Sugo do?"),
        N_(
            "It turns a document into compact Markdown for AI models and RAG systems. It "
            "removes what only costs tokens, such as repeated headers and footers, page "
            "numbers, hidden text and tracking parameters, without losing content."
        ),
    ),
    (
        N_("Do my files leave this computer?"),
        N_(
            "No. Sugo converts on this computer, and this page talks only to Sugo, here. "
            "Nothing is sent to the internet."
        ),
    ),
    (
        N_("Which files can I convert?"),
        N_(
            "PDF, DOCX, XLSX and PPTX up to {large} MB; PNG, JPEG, WEBP and XML up to {small} "
            "MB. Old .doc, .xls and .ppt files and password-protected files are not read: "
            "save a new copy first."
        ),
    ),
    (
        N_("What are tokens?"),
        N_(
            "The pieces of text AI models count and bill. Fewer tokens cost less and leave "
            "more room in the model's context. Sugo counts them with one tokenizer, "
            "o200k_base; other providers count a little differently."
        ),
    ),
    (
        N_("Why are some blocks removed?"),
        N_(
            "Each cleaner removes one kind of noise, and the page shows how many blocks "
            "each one removed. Text that cannot be read is marked as illegible, never "
            "guessed."
        ),
    ),
    (
        N_("What are chunks?"),
        N_(
            "Pieces of the document of about the size you choose, each with its headings "
            "and pages, ready for a vector database. Save them as .jsonl, the same format "
            "as sugo convert --chunks."
        ),
    ),
    (
        N_("What are the languages of my documents for?"),
        N_(
            "Sugo applies their text rules when cleaning: in Italian and French, for "
            'example, it rejoins "dell\' albero" into "dell\'albero". Sugo never guesses '
            "the language."
        ),
    ),
    (
        N_("Where are my settings kept?"),
        N_(
            "The choices made here stay in this browser. The base settings come from your "
            "configuration file; sugo doctor shows where it is."
        ),
    ),
    (
        N_("How do I stop Sugo?"),
        N_("Press Ctrl+C in the terminal where sugo ui runs. Closing this page is not enough."),
    ),
    (
        N_("Can I do the same from the command line?"),
        N_(
            "Yes: sugo FILE converts, sugo stats FILE shows the tokens per provider, and "
            "sugo convert FILE --chunks makes chunks."
        ),
    ),
)


def render_page(settings: Settings) -> bytes:
    """The page, with its text in every interface language and the user's settings."""
    data = {
        "language": i18n.active_language(),
        "texts": {language: _texts(language) for language in i18n.LANGUAGES},
        "defaults": defaults(settings),
        "packs": sorted(PACKS),
        "max_bytes": MAX_INPUT_BYTES,
        "chunk_min": CHUNK_MIN_TOKENS,
        "chunk_max": CHUNK_MAX_TOKENS_LIMIT,
    }
    page = Template(_resource("index.html").decode("utf-8")).substitute(
        lang=i18n.active_language(),
        # Escaped for an attribute: quotes and angle brackets become entities.
        data=html.escape(json.dumps(data), quote=True),
    )
    return page.encode("utf-8")


def defaults(settings: Settings) -> dict[str, Any]:
    """The options a conversion uses when the page sends none: the user's configuration."""
    return {
        "ui_language": i18n.active_language(),
        "languages": list(settings.languages),
        "strip_tracking_urls": settings.cleaning.strip_tracking_urls,
        "chunks": False,
        "chunk_tokens": settings.chunking.max_tokens,
    }


def static_file(path: str) -> tuple[bytes, str] | None:
    """The content and media type of a static file, or None if there is none."""
    entry = STATIC.get(path)
    if entry is None:
        return None
    name, media_type = entry
    return _resource(name), media_type


def _texts(language: str) -> dict[str, Any]:
    sizes = {
        "large": _LARGE_MB,
        "small": _SMALL_MB,
        "size": MAX_INPUT_BYTES // _MB,
        "min": CHUNK_MIN_TOKENS,
        "max": CHUNK_MAX_TOKENS_LIMIT,
    }

    def filled(text: str) -> str:
        # Only the placeholders known here; the script fills the others.
        for name, value in sizes.items():
            text = text.replace("{" + name + "}", str(value))
        return text

    texts: dict[str, Any] = {
        key: filled(i18n.translate(language, text)) for key, text in _TEXTS.items()
    }
    texts["questions"] = [
        [i18n.translate(language, question), filled(i18n.translate(language, answer))]
        for question, answer in _QUESTIONS
    ]
    return texts


@cache
def _resource(name: str) -> bytes:
    return resources.files("sugo.ports.web").joinpath("static", name).read_bytes()
