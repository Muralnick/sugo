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
    MAX_RECEIPT_BYTES,
    MAX_XML_FILE_BYTES,
)
from sugo.i18n import N_
from sugo.languages.packs import PACKS

_MB = 1024 * 1024
_LARGE_MB = max(MAX_PDF_FILE_BYTES, MAX_OFFICE_FILE_BYTES) // _MB
_SMALL_MB = max(MAX_IMAGE_FILE_BYTES, MAX_XML_FILE_BYTES) // _MB
# Files the page converts in one batch, one request each (ADR-059).
MAX_BATCH_FILES = 50

# Files served as they are, by URL path: (file name, media type).
STATIC = {
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/app.css": ("app.css", "text/css; charset=utf-8"),
    "/favicon.svg": ("favicon.svg", "image/svg+xml"),
}

# Text the script fills its placeholders into: {before}, {after}, {saved},
# {pages}, {count}, {provider}, {hint}, {tokens}, {number}, {shown}, {page} and
# {confidence}. {large},
# {small}, {size}, {min} and {max} are filled here.
_TEXTS = {
    "tagline": N_("Documents, reduced: drop a file to get its compact Markdown."),
    "tab_convert": N_("Convert"),
    "tab_verify": N_("Verify"),
    "tab_settings": N_("Settings"),
    "tab_questions": N_("Questions"),
    "drop": N_("Drop files here"),
    "choose": N_("Choose files"),
    "batch_title": N_("Files: {done} of {count} converted"),
    "batch_too_many": N_("Choose at most {max_files} files at a time."),
    "state_waiting": N_("waiting"),
    "state_converting": N_("converting…"),
    "state_done": N_("done"),
    "state_refused": N_("refused"),
    "save_all": N_("Save all (.zip)"),
    "paste": N_("Paste a screenshot"),
    "paste_hint": N_("Or press Ctrl+V on this page to convert the image in the clipboard."),
    "paste_none": N_("The clipboard holds no image."),
    "paste_denied": N_("The browser did not allow reading the clipboard; press Ctrl+V instead."),
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
    "edited_title": N_("Text edits, per cleaner"),
    "edited_none": N_("No text edited."),
    "receipt_title": N_("Receipt"),
    "receipt_intro": N_(
        "What Sugo removed or changed, with the reason, and the blocks it was not sure it "
        "read correctly. Save it to check this conversion later with sugo verify."
    ),
    "save_receipt": N_("Save receipt"),
    "receipt_removed": N_("Removed blocks ({count})"),
    "receipt_edited": N_("Edited text ({count})"),
    "receipt_flagged": N_("Uncertain blocks ({count})"),
    "receipt_none": N_("None."),
    "receipt_more": N_("Only the first {shown} are shown; the saved receipt has all {count}."),
    "receipt_page": N_("page {page}"),
    "receipt_confidence": N_("confidence {confidence}"),
    "receipt_no_text": N_("(no text)"),
    "verify_intro": N_(
        "Check that converting a file still gives what its receipt recorded, as sugo verify "
        "does. Nothing is saved."
    ),
    "verify_document": N_("Document"),
    "verify_receipt": N_("Its receipt (.receipt.json)"),
    "verify_run": N_("Verify"),
    "verifying": N_("Verifying…"),
    "verify_missing_files": N_("Choose both the document and its receipt."),
    "receipt_too_large": N_("This receipt is larger than {receipt_size} MB."),
    "verify_match": N_("The conversion is unchanged: it matches the receipt."),
    "verify_mismatch": N_("The conversion does not match the receipt. Differences: {count}"),
    "verify_drifted": N_(
        "The receipt was made with another Sugo version, so an exact match is not guaranteed."
    ),
    "diff_removed": N_("removed block"),
    "diff_edited": N_("edited text"),
    "diff_flagged": N_("uncertain block"),
    "diff_missing": N_("in the receipt, not now"),
    "diff_extra": N_("now, not in the receipt"),
    "diff_block": N_("page {page}, block {block}"),
    "diff_tokens": N_("Tokens after cleaning: {stored} in the receipt, {fresh} now"),
    "edit_before": N_("Before"),
    "edit_after": N_("After"),
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
    "keep_cache": N_(
        "Keep a cache on disk: faster next time, but it holds the text of converted documents"
    ),
    "cache_off_config": N_("The cache is off in your configuration file."),
    "doctor_title": N_("Installation"),
    "health_problem": N_("Sugo is not installed correctly, so some files may not convert:"),
    "health_details": N_("See the installation check"),
    "doctor_run": N_("Check installation"),
    "doctor_running": N_("Checking…"),
    "doctor_failed": N_("The check could not run; the terminal running sugo ui may say more."),
    "status_ok": N_("ok"),
    "status_warning": N_("warning"),
    "status_error": N_("error"),
    "make_receipt": N_("Also make a receipt: every block removed or edited, with its reason"),
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
        N_("Can I convert several files at once?"),
        N_(
            "Yes, up to {max_files} at a time: drop or choose them together. They are "
            "converted one after the other, and a file that fails does not stop the others. "
            "Click a file to see its result; Save all puts every result into one .zip file. "
            "Nothing is kept after you close the page."
        ),
    ),
    (
        N_("What is the receipt?"),
        N_(
            "A record of the conversion: every block Sugo removed and every text it edited, "
            "with the reason and the original text, and the blocks it was not sure it read "
            "correctly. Turn it on in Settings. Later, sugo verify FILE RECEIPT checks that "
            "converting the same file still gives the same result."
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


def render_page(settings: Settings, language: str) -> bytes:
    """The page, with its text in every interface language and the user's settings.

    ``language`` is the interface language the server started in.
    """
    data = {
        "language": language,
        "texts": {name: _texts(name) for name in i18n.LANGUAGES},
        "defaults": defaults(settings, language),
        "packs": sorted(PACKS),
        "max_bytes": MAX_INPUT_BYTES,
        "max_receipt_bytes": MAX_RECEIPT_BYTES,
        "max_batch_files": MAX_BATCH_FILES,
        "chunk_min": CHUNK_MIN_TOKENS,
        "chunk_max": CHUNK_MAX_TOKENS_LIMIT,
    }
    page = Template(_resource("index.html").decode("utf-8")).substitute(
        lang=language,
        # Escaped for an attribute: quotes and angle brackets become entities.
        data=html.escape(json.dumps(data), quote=True),
    )
    return page.encode("utf-8")


def defaults(settings: Settings, language: str) -> dict[str, Any]:
    """The options a conversion uses when the page sends none: the user's configuration."""
    return {
        "ui_language": language,
        "languages": list(settings.languages),
        "strip_tracking_urls": settings.cleaning.strip_tracking_urls,
        "chunks": False,
        "receipt": False,
        "cache": settings.storage.cache == "persistent",
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
        "receipt_size": MAX_RECEIPT_BYTES // _MB,
        "max_files": MAX_BATCH_FILES,
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
