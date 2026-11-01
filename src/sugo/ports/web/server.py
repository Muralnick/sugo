"""The web UI's HTTP server: the standard library's, on 127.0.0.1 only (ADR-055).

Sugo serves its page, style and script, and one API route that converts the
bytes of the file the user dropped. Every request must name the server
itself in ``Host`` (against DNS rebinding). API requests must also come from
the server's own ``Origin`` and carry the session token in ``X-Sugo-Token``,
compared in constant time: the token reaches the page only in the URL
fragment, and a custom header forces a CORS preflight, which the server never
answers with CORS headers. Uploads need a ``Content-Length`` within the size
limits, checked before reading; one conversion runs at a time.

Every refusal is ``WEB_REQUEST_REFUSED``, with one message whatever the
check. The access log is off; failures are logged by exception type only,
never with document text or file names.
"""

import hmac
import json
import logging
import secrets
import socket
import socketserver
import sys
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import TYPE_CHECKING, Any

from sugo.core.constants import MAX_INPUT_BYTES, WEB_SOCKET_TIMEOUT_S, WEB_TOKEN_BYTES
from sugo.ports.errors import PortError, from_exception, web_request_refused
from sugo.ports.web.page import render_page, static_file

if TYPE_CHECKING:
    from sugo.config.settings import Settings
    from sugo.storage.page_cache import PageCache

_log = logging.getLogger(__name__)

LOOPBACK = "127.0.0.1"
TOKEN_HEADER = "X-Sugo-Token"  # noqa: S105 - a header name, not a secret
CONVERT_PATH = "/api/convert"

# On every response, error pages included.
_SECURITY_HEADERS = (
    (
        "Content-Security-Policy",
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; "
        "connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none'; "
        "frame-ancestors 'none'",
    ),
    ("X-Content-Type-Options", "nosniff"),
    ("Referrer-Policy", "no-referrer"),
    ("Cache-Control", "no-store"),
    ("X-Frame-Options", "DENY"),
    ("Cross-Origin-Opener-Policy", "same-origin"),
    ("Cross-Origin-Resource-Policy", "same-origin"),
)

# Turns a file's bytes into the JSON the page shows.
Converter = Callable[[bytes], dict[str, Any]]


class _Refused(Exception):  # noqa: N818 - a signal, not an error the user sees
    """A request one of the protections refused, with the HTTP status to answer."""

    def __init__(self, status: HTTPStatus) -> None:
        super().__init__(status.phrase)
        self.status = status


class WebServer(ThreadingHTTPServer):
    """Serves the page and the conversion API on a port the system chooses."""

    daemon_threads = True
    # On Windows, SO_REUSEADDR would let another program bind the same port.
    allow_reuse_address = False

    def __init__(self, converter: Converter) -> None:
        super().__init__((LOOPBACK, 0), _Handler)
        self.converter = converter
        self.token = secrets.token_urlsafe(WEB_TOKEN_BYTES)
        port = self.server_address[1]
        self.port = port
        self.hosts = frozenset({f"{LOOPBACK}:{port}", f"localhost:{port}"})
        self.origins = frozenset(f"http://{host}" for host in self.hosts)
        self.busy = threading.Lock()

    @property
    def url(self) -> str:
        """The address to open: the token is in the fragment, never sent to a server."""
        return f"http://{LOOPBACK}:{self.port}/#token={self.token}"

    def server_bind(self) -> None:
        """Bind without the reverse DNS lookup ``HTTPServer`` makes for its name."""
        if sys.platform == "win32":
            # Nobody else may bind this port while Sugo holds it.
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        socketserver.TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name = str(host)
        self.server_port = int(port)

    def handle_error(self, request: Any, client_address: Any) -> None:
        """Log a failed connection by type only; the default prints a traceback."""
        _log.warning("a web request failed: %s", type(sys.exc_info()[1]).__name__)


class _Handler(BaseHTTPRequestHandler):
    server: WebServer
    # Idle seconds before a stalled connection is dropped (slow senders).
    timeout = WEB_SOCKET_TIMEOUT_S

    def version_string(self) -> str:
        return "sugo"

    def log_message(self, format: str, *args: Any) -> None:
        """The access log is off: request lines are nobody's business (ADR-055)."""

    def send_error(self, code: int, message: str | None = None, explain: str | None = None) -> None:
        """Answer a malformed request with its status only, echoing nothing back."""
        self.close_connection = True
        self._send(HTTPStatus(code), b"")

    def end_headers(self) -> None:
        for name, value in _SECURITY_HEADERS:
            self.send_header(name, value)
        super().end_headers()

    def do_GET(self) -> None:
        try:
            self._check_host()
        except _Refused as refused:
            self._refuse(refused.status)
            return
        if self.path == "/":
            self._send(HTTPStatus.OK, render_page(), "text/html; charset=utf-8")
            return
        found = static_file(self.path)
        if found is None:
            self._send(HTTPStatus.NOT_FOUND, b"")
            return
        content, media_type = found
        self._send(HTTPStatus.OK, content, media_type)

    def do_POST(self) -> None:
        try:
            self._check_host()
            if self.path != CONVERT_PATH:
                self._send(HTTPStatus.NOT_FOUND, b"")
                return
            self._check_origin_and_token()
            length = self._content_length()
            with self._one_at_a_time():
                data = self.rfile.read(length)
                if len(data) != length:
                    # The client closed the connection early: nothing to answer.
                    self.close_connection = True
                    return
                self._convert(data)
        except _Refused as refused:
            self._refuse(refused.status)

    def do_OPTIONS(self) -> None:
        # A CORS preflight: never allowed, so no cross-site request follows it.
        self._refuse(HTTPStatus.FORBIDDEN)

    def _check_host(self) -> None:
        hosts = self.headers.get_all("Host") or []
        if len(hosts) != 1 or hosts[0].lower() not in self.server.hosts:
            raise _Refused(HTTPStatus.FORBIDDEN)

    def _check_origin_and_token(self) -> None:
        origins = self.headers.get_all("Origin") or []
        tokens = self.headers.get_all(TOKEN_HEADER) or []
        if len(origins) != 1 or origins[0].lower() not in self.server.origins:
            raise _Refused(HTTPStatus.FORBIDDEN)
        expected = self.server.token.encode("ascii")
        given = tokens[0].encode("utf-8", "surrogateescape") if len(tokens) == 1 else b""
        # Constant time on mismatched lengths too, so the token's length leaks nothing.
        if not hmac.compare_digest(given, expected):
            raise _Refused(HTTPStatus.FORBIDDEN)

    def _content_length(self) -> int:
        if self.headers.get_all("Transfer-Encoding"):
            raise _Refused(HTTPStatus.LENGTH_REQUIRED)
        lengths = self.headers.get_all("Content-Length") or []
        if len(lengths) != 1 or not lengths[0].isascii() or not lengths[0].isdigit():
            raise _Refused(HTTPStatus.LENGTH_REQUIRED)
        length = int(lengths[0])
        if length > MAX_INPUT_BYTES:
            raise _Refused(HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
        return length

    @contextmanager
    def _one_at_a_time(self) -> Iterator[None]:
        if not self.server.busy.acquire(blocking=False):
            raise _Refused(HTTPStatus.CONFLICT)
        try:
            yield
        finally:
            self.server.busy.release()

    def _convert(self, data: bytes) -> None:
        try:
            result = self.server.converter(data)
        except Exception as error:  # noqa: BLE001 - the server outlives a failing file
            failure = error if isinstance(error, PortError) else from_exception(error)
            if failure is None:
                # A bug: logged without its message, which could quote the document.
                _log.error("conversion failed: %s", type(error).__name__)
                self._send(HTTPStatus.INTERNAL_SERVER_ERROR, b"")
                return
            self._send_json(HTTPStatus.UNPROCESSABLE_ENTITY, {"error": failure.as_json()})
            return
        self._send_json(HTTPStatus.OK, result)

    def _refuse(self, status: HTTPStatus) -> None:
        # The body may be unread: the connection cannot carry another request.
        self.close_connection = True
        self._send_json(status, {"error": web_request_refused().as_json()})

    def _send_json(self, status: HTTPStatus, value: object) -> None:
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8")

    def _send(self, status: HTTPStatus, body: bytes, media_type: str | None = None) -> None:
        self.send_response(status)
        if media_type is not None:
            self.send_header("Content-Type", media_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def converter(settings: "Settings") -> Converter:
    """Convert uploads with the user's settings, measuring tokens per provider."""

    def convert(data: bytes) -> dict[str, Any]:
        from sugo.core import pipeline
        from sugo.core.estimate import estimate_json, estimate_savings
        from sugo.metrics.providers import list_providers
        from sugo.metrics.tokenizer import count_tokens

        with _page_cache(enabled=settings.storage.cache == "persistent") as cache:
            conversion = pipeline.convert(
                data,
                cache=cache,
                count_raw_tokens=True,
                languages=settings.languages,
                strip_tracking_urls=settings.cleaning.strip_tracking_urls,
            )
        estimate = estimate_savings(data, conversion, list_providers())
        return {
            "kind": conversion.kind.value,
            "pages": conversion.pages,
            "failed_pages": list(conversion.failed_pages),
            "markdown": conversion.markdown,
            "tokens": count_tokens(conversion.markdown),
            "removed": dict(conversion.removed),
            **estimate_json(estimate),
        }

    return convert


@contextmanager
def _page_cache(*, enabled: bool) -> Iterator["PageCache | None"]:
    """The persistent page cache, opened in the converting thread (SQLite needs that)."""
    if not enabled:
        yield None
        return
    from sugo.storage.page_cache import CacheUnavailableError, PageCache
    from sugo.storage.paths import StorageDirError

    try:
        cache = PageCache.default()
    except (CacheUnavailableError, StorageDirError, OSError):
        _log.warning("the page cache is unavailable; using a temporary one")
        yield None
        return
    with cache:
        yield cache
