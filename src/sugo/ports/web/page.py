"""The page, its style and script, shipped inside the package (ADR-055).

Nothing is loaded from the internet: no CDN, font or analytics, so the page
works offline and sends nothing out. Its text is Sugo's own, translated here
into the interface language and handed to the script as one JSON value in a
``<meta>`` attribute; the script inserts every text with ``textContent``.
"""

import html
import json
from functools import cache
from importlib import resources
from string import Template

from sugo import i18n
from sugo.core.constants import MAX_INPUT_BYTES
from sugo.i18n import N_

# Files served as they are, by URL path: (file name, media type).
STATIC = {
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/app.css": ("app.css", "text/css; charset=utf-8"),
}

# Text the script fills its placeholders into: {before}, {after}, {saved},
# {pages}, {count}, {provider}, {hint}, {code} and {message}.
_TEXTS = {
    "tagline": N_("Documents, reduced: drop a file to get its compact Markdown."),
    "drop": N_("Drop a file here"),
    "choose": N_("Choose a file"),
    "formats": N_("PDF, DOCX, XLSX, PPTX, PNG, JPEG, WEBP or XML, up to {size} MB."),
    "too_large": N_("This file is larger than {size} MB."),
    "empty": N_("This file is empty."),
    "converting": N_("Converting…"),
    "markdown": N_("Markdown"),
    "copy": N_("Copy"),
    "copied": N_("Copied"),
    "copy_failed": N_("The browser did not allow copying; select the text and copy it."),
    "save": N_("Save as .md"),
    "tokens": N_("Tokens"),
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
    "pages": N_("Pages: {count}"),
    "failed_pages": N_("Pages that could not be read: {pages}"),
    "removed_title": N_("Blocks removed, per cleaner"),
    "removed_none": N_("No blocks removed."),
    "error": N_("error"),
    "hint": N_("hint: {hint}"),
    "unexpected": N_("Something went wrong; the terminal running sugo ui may say more."),
    "no_token": N_("Open the address sugo ui printed in the terminal."),
    "local_only": N_("Sugo runs on this computer only. To stop it, press Ctrl+C in the terminal."),
}


def render_page() -> bytes:
    """The page in the interface language."""
    size = MAX_INPUT_BYTES // (1024 * 1024)
    texts = {key: i18n.gettext(text) for key, text in _TEXTS.items()}
    texts["formats"] = texts["formats"].format(size=size)
    texts["too_large"] = texts["too_large"].format(size=size)
    page = Template(_resource("index.html").decode("utf-8")).substitute(
        lang=i18n.active_language(),
        # Escaped for an attribute: quotes and angle brackets become entities.
        texts=html.escape(json.dumps({**texts, "max_bytes": MAX_INPUT_BYTES}), quote=True),
    )
    return page.encode("utf-8")


def static_file(path: str) -> tuple[bytes, str] | None:
    """The content and media type of a static file, or None if there is none."""
    entry = STATIC.get(path)
    if entry is None:
        return None
    name, media_type = entry
    return _resource(name), media_type


@cache
def _resource(name: str) -> bytes:
    return resources.files("sugo.ports.web").joinpath("static", name).read_bytes()
