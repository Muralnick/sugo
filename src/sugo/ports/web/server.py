"""The web UI's HTTP server: the standard library's, on 127.0.0.1 only (ADR-055).

Sugo serves its page, style and script, and one API route that converts the
bytes of the file the user dropped. Every request must name the server
itself in ``Host`` (against DNS rebinding). API requests must also come from
the server's own ``Origin`` and carry the session token in ``X-Sugo-Token``,
compared in constant time: the token reaches the page only in the URL
fragment, and a custom header forces a CORS preflight, which the server never
answers with CORS headers. Uploads need a ``Content-Length`` within the size
limits, checked before reading; one conversion runs at a time. The page's
settings come as one header each, checked against the known values; the
server keeps nothing between conversions and writes nothing to disk.

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
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from sugo import i18n
from sugo.config.settings import Settings
from sugo.core.constants import (
    CHUNK_MAX_TOKENS_LIMIT,
    CHUNK_MIN_TOKENS,
    MAX_INPUT_BYTES,
    WEB_SOCKET_TIMEOUT_S,
    WEB_TOKEN_BYTES,
    WEB_UPLOAD_TIMEOUT_S,
)
from sugo.languages.packs import PACKS
from sugo.ports.cache import page_cache
from sugo.ports.errors import PortError, from_exception, web_request_refused
from sugo.ports.web.page import render_page, static_file

_log = logging.getLogger(__name__)

LOOPBACK = "127.0.0.1"
TOKEN_HEADER = "X-Sugo-Token"  # noqa: S105 - a header name, not a secret
CONVERT_PATH = "/api/convert"
# Bytes read from the socket at a time.
_READ_BYTES = 1024 * 1024

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

# The page's settings, one header each (ADR-055).
LANGUAGE_HEADER = "X-Sugo-Language"
LANGUAGES_HEADER = "X-Sugo-Languages"
TRACKING_HEADER = "X-Sugo-Strip-Tracking"
CHUNKS_HEADER = "X-Sugo-Chunk-Tokens"
_BOOLEANS = {"true": True, "false": False}


@dataclass(frozen=True)
class Options:
    """How to convert one upload: the user's configuration, changed by the page."""

    # Interface language of the messages in the answer.
    language: str
    # Language packs whose text rules apply.
    languages: tuple[str, ...]
    strip_tracking_urls: bool
    # Chunk size in tokens; None makes no chunks.
    chunk_tokens: int | None


# Turns a file's bytes into the JSON the page shows.
Converter = Callable[[bytes, Options], dict[str, Any]]


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

    def __init__(self, converter: Converter, settings: Settings) -> None:
        super().__init__((LOOPBACK, 0), _Handler)
        self.converter = converter
        self.settings = settings
        # Fixed at start: a conversion switches the process's language for
        # its own messages, which other threads must not pick up.
        self.language = i18n.active_language()
        self.refusal = {"error": web_request_refused().as_json()}
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
            page = render_page(self.server.settings, self.server.language)
            self._send(HTTPStatus.OK, page, "text/html; charset=utf-8")
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
            try:
                options = self._options()
            except _Refused:
                # Drained, so the page sees the refusal (see _one_at_a_time).
                self._read_body(length)
                raise
            with self._one_at_a_time(length):
                data = self._read_body(length)
                if data is None:
                    # The client stopped sending: nothing to answer.
                    self.close_connection = True
                    return
                with _speaking(options.language):
                    self._convert(data, options)
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
        # Constant time for tokens of the right length; the length itself is public.
        if not hmac.compare_digest(given, expected):
            raise _Refused(HTTPStatus.FORBIDDEN)

    def _content_length(self) -> int:
        if self.headers.get_all("Transfer-Encoding"):
            raise _Refused(HTTPStatus.LENGTH_REQUIRED)
        lengths = self.headers.get_all("Content-Length") or []
        if len(lengths) != 1 or not lengths[0].isascii() or not lengths[0].isdigit():
            raise _Refused(HTTPStatus.LENGTH_REQUIRED)
        # Too many digits is too large, and int() refuses more than 4 300 of them.
        if len(lengths[0].lstrip("0")) > len(str(MAX_INPUT_BYTES)):
            raise _Refused(HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
        length = int(lengths[0])
        if length > MAX_INPUT_BYTES:
            raise _Refused(HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
        return length

    def _options(self) -> Options:
        """The page's settings; a header that is repeated or holds an unknown value is refused."""
        settings = self.server.settings
        language = self._single(LANGUAGE_HEADER)
        if language is None:
            language = self.server.language
        elif language not in i18n.LANGUAGES:
            raise _Refused(HTTPStatus.BAD_REQUEST)
        named = self._single(LANGUAGES_HEADER)
        if named is None:
            languages = settings.languages
        else:
            codes = named.split(",")
            if not codes or any(code not in PACKS for code in codes):
                raise _Refused(HTTPStatus.BAD_REQUEST)
            languages = tuple(sorted(set(codes)))
        tracking = self._single(TRACKING_HEADER)
        if tracking is not None and tracking not in _BOOLEANS:
            raise _Refused(HTTPStatus.BAD_REQUEST)
        size = self._single(CHUNKS_HEADER)
        chunk_tokens = None
        if size is not None:
            if not (
                size.isascii() and size.isdigit() and len(size) <= len(str(CHUNK_MAX_TOKENS_LIMIT))
            ):
                raise _Refused(HTTPStatus.BAD_REQUEST)
            chunk_tokens = int(size)
            if not CHUNK_MIN_TOKENS <= chunk_tokens <= CHUNK_MAX_TOKENS_LIMIT:
                raise _Refused(HTTPStatus.BAD_REQUEST)
        return Options(
            language=language,
            languages=languages,
            strip_tracking_urls=(
                settings.cleaning.strip_tracking_urls if tracking is None else _BOOLEANS[tracking]
            ),
            chunk_tokens=chunk_tokens,
        )

    def _single(self, name: str) -> str | None:
        """A header sent at most once, or None if absent."""
        values = self.headers.get_all(name) or []
        if len(values) > 1:
            raise _Refused(HTTPStatus.BAD_REQUEST)
        return values[0] if values else None

    @contextmanager
    def _one_at_a_time(self, length: int) -> Iterator[None]:
        if not self.server.busy.acquire(blocking=False):
            # Read and drop the body first: closing with unread data can reset
            # the connection, and the page would never see the refusal. Only a
            # request with the token gets here, and its size is within limits.
            self._read_body(length)
            raise _Refused(HTTPStatus.CONFLICT)
        try:
            yield
        finally:
            self.server.busy.release()

    def _read_body(self, length: int) -> bytes | None:
        """The body, or None if it is cut short or takes too long in all.

        The socket timeout bounds each wait; the deadline bounds the whole
        upload, so a client sending a byte now and then cannot hold the server.
        """
        deadline = time.monotonic() + WEB_UPLOAD_TIMEOUT_S
        parts: list[bytes] = []
        remaining = length
        while remaining > 0:
            if time.monotonic() > deadline:
                return None
            part = self.rfile.read1(min(remaining, _READ_BYTES))
            if not part:
                return None
            parts.append(part)
            remaining -= len(part)
        return b"".join(parts)

    def _convert(self, data: bytes, options: Options) -> None:
        try:
            result = self.server.converter(data, options)
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
        self._send_json(status, self.server.refusal)

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


def converter(settings: Settings) -> Converter:
    """Convert uploads with the page's options, measuring tokens per provider."""

    def convert(data: bytes, options: Options) -> dict[str, Any]:
        from sugo.core import pipeline
        from sugo.core.estimate import estimate_json, estimate_savings
        from sugo.exporters.jsonl import jsonl_lines
        from sugo.metrics.providers import list_providers

        with page_cache(enabled=settings.storage.cache == "persistent") as cache:
            conversion = pipeline.convert(
                data,
                cache=cache,
                count_raw_tokens=True,
                max_chunk_tokens=options.chunk_tokens,
                languages=options.languages,
                strip_tracking_urls=options.strip_tracking_urls,
            )
        estimate = estimate_savings(data, conversion, list_providers())
        # Kind, pages and token counts come from the estimate.
        result: dict[str, Any] = {
            **estimate_json(estimate),
            "failed_pages": list(conversion.failed_pages),
            "markdown": conversion.markdown,
            "removed": dict(conversion.removed),
        }
        if options.chunk_tokens is not None:
            result["chunk_tokens"] = options.chunk_tokens
            # The file sugo convert --chunks writes, byte for byte; the page
            # reads the chunks from its lines.
            result["jsonl"] = "".join(jsonl_lines(conversion.chunks))
        return result

    return convert


@contextmanager
def _speaking(language: str) -> Iterator[None]:
    """Messages made inside are in ``language``; only one conversion runs at a time."""
    previous = i18n.active_language()
    i18n.activate(language)
    try:
        yield
    finally:
        i18n.activate(previous)
