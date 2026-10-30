"""Remove tracking parameters from URLs in the text (ADR-050).

"https://example.com/offer?utm_source=newsletter&id=7" tells an LLM nothing
more than "https://example.com/offer?id=7", and costs more tokens. This
cleaner proposes to delete only the parameters on a fixed list of trackers
(``TRACKING_PARAMETERS``, ``utm_*``); the address and every other parameter
stay, so the link still works. Each deleted parameter is recorded on the
block with the reason below (principle 3).

Only ``http`` and ``https`` URLs in prose are touched; code, tables and
formulas are left alone, like the other text cleaners.
"""

import re
from collections.abc import Iterator
from itertools import islice
from typing import ClassVar

from sugo.analyzers.lexicon import Lexicon
from sugo.cleaners.text_normalization import TEXT_TYPES
from sugo.core.constants import (
    MAX_EDITS_PER_BLOCK,
    TRACKING_PARAMETER_PREFIXES,
    TRACKING_PARAMETERS,
)
from sugo.core.decisions import EditDecision, within_limits
from sugo.core.models import EditKind, Page

REASON = "tracking parameter in a URL"

_URL = re.compile(r"https?://[^\s<>\"'`\[\]{}|\\^]+", re.IGNORECASE)
# Punctuation that ends a sentence rather than the URL: "see https://a.b/c."
_TRAILING = ".,;:!?)'\"\u00bb\u201d\u2019"


class TrackingUrlCleaner:
    """Proposes deleting tracking parameters from the URLs of a page's prose."""

    name: ClassVar[str] = "tracking_urls"

    def propose(self, page: Page, stats: Lexicon) -> list[EditDecision]:
        """Return one deletion per run of tracking parameters.

        ``stats`` is part of the cleaner contract and unused here: this
        cleaner needs no document-wide context.
        """
        return within_limits(
            # One past the limit is enough to know the block is left as it is.
            list(islice(_block_edits(block.id, block.text), MAX_EDITS_PER_BLOCK + 1))
            for block in page.blocks
            if not block.removed and block.type in TEXT_TYPES
        )


def _block_edits(block_id: str, text: str) -> Iterator[EditDecision]:
    for match in _URL.finditer(text):
        for start, end in tracking_spans(match.group().rstrip(_TRAILING), match.start()):
            yield EditDecision(
                block_id=block_id,
                start=start,
                end=end,
                replacement="",
                kind=EditKind.DELETE,
                reason=REASON,
            )


def tracking_spans(url: str, offset: int = 0) -> list[tuple[int, int]]:
    """Spans of ``url`` (shifted by ``offset``) to delete, so no tracking parameter is left.

    Consecutive tracking parameters are deleted as one span with their
    separators, so the URL stays well formed: "?a=1&utm_x=2&utm_y=3" loses
    "&utm_x=2&utm_y=3", and "?utm_x=2" loses the "?" too.
    """
    question = url.find("?")
    if question < 0:
        return []
    fragment = url.find("#", question)
    query_end = len(url) if fragment < 0 else fragment
    params: list[tuple[int, int, bool]] = []
    position = question + 1
    for part in url[question + 1 : query_end].split("&"):
        params.append((position, position + len(part), _is_tracking(part)))
        position += len(part) + 1
    if not any(tracking for _, _, tracking in params):
        return []
    if all(tracking for _, _, tracking in params):
        return [(offset + question, offset + query_end)]
    spans: list[tuple[int, int]] = []
    index = 0
    while index < len(params):
        if not params[index][2]:
            index += 1
            continue
        last = index
        while last + 1 < len(params) and params[last + 1][2]:
            last += 1
        if last + 1 < len(params):
            # Up to the next kept parameter: takes the "&" after the run.
            spans.append((params[index][0], params[last + 1][0]))
        else:
            # A run at the end: takes the "&" before it instead.
            spans.append((params[index - 1][1], params[last][1]))
        index = last + 1
    return [(offset + start, offset + end) for start, end in spans]


def _is_tracking(parameter: str) -> bool:
    name = parameter.split("=", 1)[0].casefold()
    return name in TRACKING_PARAMETERS or name.startswith(TRACKING_PARAMETER_PREFIXES)
