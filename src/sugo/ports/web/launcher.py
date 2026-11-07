"""Open the web UI without putting its access token on a command line (security review F7).

``webbrowser.open`` starts the browser, or ``xdg-open``, with the address as
a process argument, and on Linux every local user can read the arguments of
every process. So the browser is given a small page in a private temporary
folder instead, readable only by the user, which forwards to the address
with the token. The page is deleted when the server stops.
"""

import html
import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

_PAGE = """<!doctype html>
<meta charset="utf-8">
<meta name="referrer" content="no-referrer">
<meta http-equiv="refresh" content="0; url={url}">
<title>Sugo</title>
<a href="{url}">Sugo</a>
"""


@contextmanager
def launcher_page(url: str) -> Iterator[Path]:
    """A private page that forwards the browser to ``url``; deleted on exit."""
    # The folder is created readable only by the user, on every system.
    with tempfile.TemporaryDirectory(prefix="sugo-ui-") as folder:
        path = Path(folder) / "open-sugo.html"
        # O_EXCL: never write through a file or link that is already there.
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as page:
            page.write(_PAGE.format(url=html.escape(url, quote=True)))
        yield path
