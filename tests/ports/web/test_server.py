"""Tests for the web UI's server: the page, the conversion API and every protection (ADR-055).

Requests are written by hand on a raw socket, so the tests can send what a
browser never would: a wrong ``Host``, two tokens, no ``Content-Length``.
"""

import json
import logging
import re
import socket
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from html import unescape
from pathlib import Path
from typing import Any

import pytest

from sugo import i18n
from sugo.config.settings import Chunking, General, Settings
from sugo.core.constants import MAX_INPUT_BYTES, WEB_TOKEN_BYTES
from sugo.core.pipeline import InputUnsupportedError
from sugo.ports.web import server as web_server
from sugo.ports.web.page import render_page
from sugo.ports.web.server import (
    CHUNKS_HEADER,
    CONVERT_PATH,
    LANGUAGE_HEADER,
    LANGUAGES_HEADER,
    TOKEN_HEADER,
    TRACKING_HEADER,
    Options,
    WebServer,
    converter,
)
from sugo.storage.paths import CACHE_DIR_ENV

STATIC = Path(web_server.__file__).parent / "static"
REFUSED_MESSAGE = "The request was refused."


@dataclass
class Response:
    status: int
    headers: dict[str, str]
    body: bytes

    def json(self) -> Any:
        assert self.headers["content-type"] == "application/json; charset=utf-8"
        return json.loads(self.body)


class Recorder:
    """A converter that records what it was given and answers with a fixed result."""

    def __init__(self) -> None:
        self.calls: list[bytes] = []
        self.options: list[Options] = []
        self.release = threading.Event()
        self.release.set()
        self.started = threading.Event()
        self.raises: Exception | None = None

    def __call__(self, data: bytes, options: Options) -> dict[str, Any]:
        self.calls.append(data)
        self.options.append(options)
        self.started.set()
        assert self.release.wait(10)
        if self.raises is not None:
            raise self.raises
        return {"markdown": "# Title", "size": len(data)}


def running(
    convert: Callable[[bytes, Options], dict[str, Any]], settings: Settings | None = None
) -> Iterator[WebServer]:
    server = WebServer(convert, settings or Settings())
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05})
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)


@pytest.fixture
def recorder() -> Recorder:
    return Recorder()


@pytest.fixture
def server(recorder: Recorder) -> Iterator[WebServer]:
    yield from running(recorder)


def exchange(server: WebServer, raw: bytes, *, timeout: float = 10) -> Response:
    """Send raw bytes, read until the server closes the connection."""
    with socket.create_connection(("127.0.0.1", server.port), timeout=timeout) as connection:
        connection.sendall(raw)
        received = b""
        while chunk := connection.recv(65536):
            received += chunk
    head, _, body = received.partition(b"\r\n\r\n")
    status_line, *lines = head.decode("latin-1").split("\r\n")
    headers: dict[str, str] = {}
    for line in lines:
        name, _, value = line.partition(":")
        assert name.lower() not in headers, f"duplicate header {name}"
        headers[name.lower()] = value.strip()
    return Response(int(status_line.split()[1]), headers, body)


def request(
    server: WebServer,
    method: str = "GET",
    path: str = "/",
    *,
    headers: list[tuple[str, str]] | None = None,
    body: bytes = b"",
    host: str | None = "default",
) -> Response:
    lines = [f"{method} {path} HTTP/1.1"]
    if host == "default":
        lines.append(f"Host: 127.0.0.1:{server.port}")
    elif host is not None:
        lines.append(f"Host: {host}")
    lines += [f"{name}: {value}" for name, value in headers or []]
    return exchange(server, ("\r\n".join(lines) + "\r\n\r\n").encode("latin-1") + body)


def api_headers(server: WebServer, body: bytes) -> list[tuple[str, str]]:
    """The headers Sugo's own page sends with an upload."""
    return [
        ("Origin", f"http://127.0.0.1:{server.port}"),
        (TOKEN_HEADER, server.token),
        ("Content-Type", "application/octet-stream"),
        ("Content-Length", str(len(body))),
    ]


def upload(server: WebServer, body: bytes = b"%PDF-1.7 bytes") -> Response:
    return request(server, "POST", CONVERT_PATH, headers=api_headers(server, body), body=body)


def without(headers: list[tuple[str, str]], name: str) -> list[tuple[str, str]]:
    return [(key, value) for key, value in headers if key != name]


def replaced(headers: list[tuple[str, str]], name: str, value: str) -> list[tuple[str, str]]:
    return [*without(headers, name), (name, value)]


def assert_refused(response: Response, status: int) -> None:
    assert response.status == status
    error = response.json()["error"]
    # One message for every check: a probing page learns nothing.
    assert (error["code"], error["message"]) == ("WEB_REQUEST_REFUSED", REFUSED_MESSAGE)
    assert not any(name.startswith("access-control-") for name in response.headers)


# --- The page -------------------------------------------------------------------


def test_the_server_listens_on_loopback_with_a_fresh_token(recorder: Recorder) -> None:
    first, second = WebServer(recorder, Settings()), WebServer(recorder, Settings())
    try:
        assert first.server_address[0] == "127.0.0.1"
        assert first.port != 0
        assert first.token != second.token
        # token_urlsafe(32): 32 bytes in base64 without padding.
        assert len(first.token) == -(-WEB_TOKEN_BYTES * 4 // 3)
        assert first.url == f"http://127.0.0.1:{first.port}/#token={first.token}"
    finally:
        first.server_close()
        second.server_close()


def test_page_style_and_script_are_served_with_strict_headers(server: WebServer) -> None:
    page = request(server)
    assert page.status == 200
    assert page.headers["content-type"] == "text/html; charset=utf-8"
    assert server.token.encode() not in page.body
    csp = page.headers["content-security-policy"]
    assert "default-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp
    assert "unsafe-inline" not in csp
    assert page.headers["x-content-type-options"] == "nosniff"
    assert page.headers["referrer-policy"] == "no-referrer"
    assert page.headers["cache-control"] == "no-store"
    assert page.headers["server"] == "sugo"
    script = request(server, path="/app.js")
    assert script.headers["content-type"] == "text/javascript; charset=utf-8"
    assert script.body == (STATIC / "app.js").read_bytes()
    assert request(server, path="/app.css").headers["content-type"] == "text/css; charset=utf-8"
    icon = request(server, path="/favicon.svg")
    assert icon.headers["content-type"] == "image/svg+xml"
    assert icon.body == (STATIC / "favicon.svg").read_bytes()


@pytest.mark.parametrize(
    "path", ["/index.html", "/app.js?x=1", "/static/app.js", "/../pyproject.toml", "/api"]
)
def test_nothing_else_is_served(server: WebServer, path: str) -> None:
    response = request(server, path=path)
    assert (response.status, response.body) == (404, b"")


def test_the_page_has_no_inline_script_nor_external_resource() -> None:
    page = (STATIC / "index.html").read_text(encoding="utf-8")
    assert re.findall(r"<script[^>]*>", page) == ['<script src="/app.js" defer>']
    assert "http" not in page.lower()  # Nothing from outside: no CDN, font or analytics.
    assert re.search(r"\son[a-z]+\s*=", page) is None  # No inline event handlers.


def test_the_icon_is_a_plain_drawing() -> None:
    # An SVG file can carry scripts, links and styles; the icon has none of them.
    icon = (STATIC / "favicon.svg").read_text(encoding="utf-8").lower()
    for part in ("<script", "<style", "<a ", "<foreignobject", "<image", "href"):
        assert part not in icon
    assert re.search(r"\son[a-z]+\s*=", icon) is None  # No event handlers.


def test_the_script_never_inserts_html() -> None:
    script = (STATIC / "app.js").read_text(encoding="utf-8")
    for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval("):
        assert sink not in script
    assert "new Function" not in script


def page_data(page: bytes) -> Any:
    match = re.search(r'<meta name="sugo-data" content="([^"]*)">', page.decode("utf-8"))
    assert match is not None
    return json.loads(unescape(match.group(1)))


def test_texts_reach_the_page_escaped_in_every_language() -> None:
    page = render_page(Settings(), "it")
    assert b'<html lang="it">' in page
    data = page_data(page)
    assert data["language"] == "it"
    assert data["texts"]["it"]["choose"] == "Scegli un file"
    assert data["texts"]["en"]["choose"] == "Choose a file"
    assert data["max_bytes"] == MAX_INPUT_BYTES
    for texts in data["texts"].values():
        assert "{large}" not in texts["formats"]
        assert "{min}" not in texts["chunk_size"]
        assert len(texts["questions"]) >= 5
        assert all(question and answer for question, answer in texts["questions"])
        assert all("{" not in answer for _, answer in texts["questions"])


def test_the_page_starts_from_the_users_configuration() -> None:
    settings = Settings(general=General(languages=("de", "it")), chunking=Chunking(max_tokens=256))
    data = page_data(render_page(settings, "en"))
    assert data["defaults"] == {
        "ui_language": "en",
        "languages": ["de", "it"],
        "strip_tracking_urls": True,
        "chunks": False,
        "chunk_tokens": 256,
    }
    assert data["packs"] == ["de", "en", "es", "fr", "it"]


# --- Host, Origin and token ----------------------------------------------------------


def test_the_page_answers_both_loopback_names(server: WebServer) -> None:
    assert request(server, host=f"localhost:{server.port}").status == 200
    assert request(server, host=f"LOCALHOST:{server.port}").status == 200


@pytest.mark.parametrize(
    "host",
    [
        None,
        "evil.example",
        "evil.example:{port}",
        "127.0.0.1",
        "127.0.0.1:1",
        "localhost",
        "127.0.0.1:{port}.evil.example",
        "[::1]:{port}",
        "0.0.0.0:{port}",
    ],
)
def test_a_foreign_host_is_refused_dns_rebinding(server: WebServer, host: str | None) -> None:
    named = None if host is None else host.format(port=server.port)
    assert_refused(request(server, host=named), 403)
    body = b"%PDF"
    response = request(
        server, "POST", CONVERT_PATH, headers=api_headers(server, body), body=body, host=named
    )
    assert_refused(response, 403)


def test_two_host_headers_are_refused(server: WebServer) -> None:
    response = request(server, headers=[("Host", "evil.example")])
    assert_refused(response, 403)


def test_an_upload_from_the_page_is_converted(server: WebServer, recorder: Recorder) -> None:
    body = bytes(range(256)) * 4
    response = upload(server, body)
    assert response.status == 200
    assert response.json() == {"markdown": "# Title", "size": len(body)}
    assert recorder.calls == [body]
    localhost = replaced(api_headers(server, body), "Origin", f"http://localhost:{server.port}")
    response = request(
        server, "POST", CONVERT_PATH, headers=localhost, body=body, host=f"localhost:{server.port}"
    )
    assert response.status == 200


@pytest.mark.parametrize(
    "change",
    [
        lambda h, s: without(h, TOKEN_HEADER),
        lambda h, s: replaced(h, TOKEN_HEADER, ""),
        lambda h, s: replaced(h, TOKEN_HEADER, s.token[:-1]),
        lambda h, s: replaced(h, TOKEN_HEADER, s.token + "x"),
        lambda h, s: replaced(h, TOKEN_HEADER, s.token.upper()),
        lambda h, s: [*h, (TOKEN_HEADER, s.token)],
        lambda h, s: replaced(h, TOKEN_HEADER, "é" + s.token[1:]),
    ],
    ids=["missing", "empty", "short", "long", "case", "twice", "non-ascii"],
)
def test_a_wrong_token_is_refused(
    server: WebServer,
    recorder: Recorder,
    change: Callable[[list[tuple[str, str]], WebServer], list[tuple[str, str]]],
) -> None:
    body = b"%PDF"
    headers = change(api_headers(server, body), server)
    assert_refused(request(server, "POST", CONVERT_PATH, headers=headers, body=body), 403)
    assert recorder.calls == []


def test_the_token_in_the_address_is_not_enough(server: WebServer, recorder: Recorder) -> None:
    body = b"%PDF"
    headers = without(api_headers(server, body), TOKEN_HEADER)
    path = f"{CONVERT_PATH}?token={server.token}"
    response = request(server, "POST", path, headers=headers, body=body)
    assert (response.status, response.body) == (404, b"")
    assert recorder.calls == []


@pytest.mark.parametrize(
    "origin",
    [
        None,
        "null",
        "http://evil.example",
        "http://127.0.0.1:{port}.evil.example",
        "https://127.0.0.1:{port}",
        "http://127.0.0.1:1",
        "http://127.0.0.1:{port}/",
    ],
)
def test_a_foreign_origin_is_refused(
    server: WebServer, recorder: Recorder, origin: str | None
) -> None:
    body = b"%PDF"
    headers = without(api_headers(server, body), "Origin")
    if origin is not None:
        headers.append(("Origin", origin.format(port=server.port)))
    assert_refused(request(server, "POST", CONVERT_PATH, headers=headers, body=body), 403)
    assert recorder.calls == []


def test_a_cors_preflight_is_never_allowed(server: WebServer) -> None:
    response = request(
        server,
        "OPTIONS",
        CONVERT_PATH,
        headers=[
            ("Origin", "http://evil.example"),
            ("Access-Control-Request-Method", "POST"),
            ("Access-Control-Request-Headers", TOKEN_HEADER.lower()),
        ],
    )
    assert_refused(response, 403)


@pytest.mark.parametrize("method", ["PUT", "DELETE", "PATCH", "HEAD", "TRACE"])
def test_other_methods_are_not_implemented(server: WebServer, method: str) -> None:
    response = request(server, method, CONVERT_PATH)
    assert response.status == 501
    assert response.body == b""
    assert response.headers["content-security-policy"].startswith("default-src 'self'")


def test_a_malformed_request_is_answered_with_its_status_only(server: WebServer) -> None:
    # http.server would echo the request line into an HTML error page.
    with socket.create_connection(("127.0.0.1", server.port), timeout=10) as connection:
        connection.sendall(b"GET /<script>alert(1)</script> HTTP/1.x\r\n\r\n")
        # The server closes after a malformed request, so read the whole answer. The
        # security headers legitimately contain "script-src": look for what was sent.
        answer = b""
        while chunk := connection.recv(65536):
            answer += chunk
    assert b"<script>" not in answer
    assert b"alert(1)" not in answer
    # Python 3.12 closes without a word on an invalid HTTP version (it treats the
    # request as HTTP/0.9); 3.13 and later answer 400. Either is fine, nothing is echoed.
    if answer:
        assert b" 400 " in answer.split(b"\r\n", 1)[0]
    raw = f"GET / HTTP/1.1\r\nHost: 127.0.0.1:{server.port}\r\nX-Long: {'a' * 70_000}\r\n\r\n"
    response = exchange(server, raw.encode())
    assert response.status == 431
    assert response.headers["content-security-policy"].startswith("default-src 'self'")
    assert response.body == b""


# --- The upload's size ------------------------------------------------------------


@pytest.mark.parametrize("length", [None, "", "-1", "+4", "4.0", "1e3", "4 4", "0x4"])
def test_an_upload_needs_a_plain_content_length(
    server: WebServer, recorder: Recorder, length: str | None
) -> None:
    body = b"%PDF"
    headers = without(api_headers(server, body), "Content-Length")
    if length is not None:
        headers.append(("Content-Length", length))
    raw_headers = "".join(f"{name}: {value}\r\n" for name, value in headers)
    raw = (
        f"POST {CONVERT_PATH} HTTP/1.1\r\nHost: 127.0.0.1:{server.port}\r\n{raw_headers}\r\n"
    ).encode() + body
    assert_refused(exchange(server, raw), 411)
    assert recorder.calls == []


def test_two_lengths_and_chunked_uploads_are_refused(server: WebServer, recorder: Recorder) -> None:
    body = b"%PDF"
    twice = [*api_headers(server, body), ("Content-Length", "4")]
    assert_refused(request(server, "POST", CONVERT_PATH, headers=twice, body=body), 411)
    chunked = [*without(api_headers(server, body), "Content-Length")]
    chunked.append(("Transfer-Encoding", "chunked"))
    response = request(
        server, "POST", CONVERT_PATH, headers=chunked, body=b"4\r\n%PDF\r\n0\r\n\r\n"
    )
    assert_refused(response, 411)
    both = [*api_headers(server, body), ("Transfer-Encoding", "chunked")]
    assert_refused(request(server, "POST", CONVERT_PATH, headers=both, body=body), 411)
    assert recorder.calls == []


def test_an_oversized_upload_is_refused_before_it_is_read(
    server: WebServer, recorder: Recorder
) -> None:
    # Only the headers are sent: the answer comes without waiting for the body.
    headers = replaced(api_headers(server, b""), "Content-Length", str(MAX_INPUT_BYTES + 1))
    raw_headers = "".join(f"{name}: {value}\r\n" for name, value in headers)
    raw = f"POST {CONVERT_PATH} HTTP/1.1\r\nHost: 127.0.0.1:{server.port}\r\n{raw_headers}\r\n"
    assert_refused(exchange(server, raw.encode(), timeout=5), 413)
    assert recorder.calls == []


@pytest.mark.parametrize("length", ["9" * 5_000, "1" + "0" * 30, "0" * 50 + "4"])
def test_a_huge_content_length_is_refused_as_too_large(
    server: WebServer, recorder: Recorder, length: str
) -> None:
    headers = replaced(api_headers(server, b""), "Content-Length", length)
    raw_headers = "".join(f"{name}: {value}\r\n" for name, value in headers)
    raw = f"POST {CONVERT_PATH} HTTP/1.1\r\nHost: 127.0.0.1:{server.port}\r\n{raw_headers}\r\n"
    response = exchange(server, raw.encode() + (b"%PDF" if length.endswith("4") else b""))
    if length.endswith("4"):
        assert response.status == 200  # Leading zeros are still a small number.
    else:
        assert_refused(response, 413)
        assert recorder.calls == []


def test_an_upload_at_the_limit_is_accepted(
    server: WebServer, recorder: Recorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(web_server, "MAX_INPUT_BYTES", 8)
    assert upload(server, b"12345678").status == 200
    assert_refused(upload(server, b"123456789"), 413)
    assert recorder.calls == [b"12345678"]


def test_a_stalled_upload_is_dropped_and_frees_the_server(
    server: WebServer, recorder: Recorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(web_server._Handler, "timeout", 0.3)
    headers = replaced(api_headers(server, b""), "Content-Length", "100")
    raw_headers = "".join(f"{name}: {value}\r\n" for name, value in headers)
    raw = f"POST {CONVERT_PATH} HTTP/1.1\r\nHost: 127.0.0.1:{server.port}\r\n{raw_headers}\r\n"
    # Ten bytes of a hundred, then silence: the server hangs up.
    response_bytes = b""
    with socket.create_connection(("127.0.0.1", server.port), timeout=5) as connection:
        connection.sendall(raw.encode() + b"0123456789")
        while chunk := connection.recv(65536):
            response_bytes += chunk
    assert response_bytes == b""
    assert recorder.calls == []
    assert upload(server).status == 200


def test_a_trickled_upload_is_dropped_at_the_deadline(
    server: WebServer, recorder: Recorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(web_server, "WEB_UPLOAD_TIMEOUT_S", 0.5)
    headers = replaced(api_headers(server, b""), "Content-Length", "100")
    raw_headers = "".join(f"{name}: {value}\r\n" for name, value in headers)
    raw = f"POST {CONVERT_PATH} HTTP/1.1\r\nHost: 127.0.0.1:{server.port}\r\n{raw_headers}\r\n"
    # One byte every 0.2 s: each wait is short, the whole upload too long.
    with socket.create_connection(("127.0.0.1", server.port), timeout=5) as connection:
        connection.sendall(raw.encode())
        stop = threading.Event()
        closed = False
        for _ in range(20):
            try:
                connection.sendall(b"x")
            except OSError:
                closed = True
                break
            if stop.wait(0.2):
                break
            connection.settimeout(0.01)
            try:
                if connection.recv(1) == b"":
                    closed = True
                    break
            except TimeoutError:
                pass
    assert closed
    assert recorder.calls == []
    assert upload(server).status == 200


# --- The page's settings ------------------------------------------------------------


def test_without_settings_the_configuration_applies(server: WebServer, recorder: Recorder) -> None:
    assert upload(server).status == 200
    assert recorder.options == [
        Options(language="en", languages=("en",), strip_tracking_urls=True, chunk_tokens=None)
    ]


def test_the_page_settings_reach_the_conversion(server: WebServer, recorder: Recorder) -> None:
    body = b"%PDF"
    headers = [
        *api_headers(server, body),
        (LANGUAGE_HEADER, "it"),
        (LANGUAGES_HEADER, "it,fr,it"),
        (TRACKING_HEADER, "false"),
        (CHUNKS_HEADER, "256"),
    ]
    assert request(server, "POST", CONVERT_PATH, headers=headers, body=body).status == 200
    assert recorder.options == [
        Options(language="it", languages=("fr", "it"), strip_tracking_urls=False, chunk_tokens=256)
    ]


@pytest.mark.parametrize(
    ("name", "value"),
    [
        (LANGUAGE_HEADER, "fr"),
        (LANGUAGE_HEADER, ""),
        (LANGUAGES_HEADER, ""),
        (LANGUAGES_HEADER, "it,,en"),
        (LANGUAGES_HEADER, "xx"),
        (LANGUAGES_HEADER, "it, en"),
        (TRACKING_HEADER, "yes"),
        (TRACKING_HEADER, "True"),
        (CHUNKS_HEADER, "31"),
        (CHUNKS_HEADER, "8193"),
        (CHUNKS_HEADER, "-64"),
        (CHUNKS_HEADER, "9" * 5_000),
        (CHUNKS_HEADER, "abc"),
    ],
)
def test_an_unknown_setting_is_refused(
    server: WebServer, recorder: Recorder, name: str, value: str
) -> None:
    body = b"%PDF"
    headers = [*api_headers(server, body), (name, value)]
    assert_refused(request(server, "POST", CONVERT_PATH, headers=headers, body=body), 400)
    assert recorder.calls == []


def test_a_repeated_setting_is_refused(server: WebServer, recorder: Recorder) -> None:
    body = b"%PDF"
    headers = [*api_headers(server, body), (LANGUAGE_HEADER, "it"), (LANGUAGE_HEADER, "en")]
    assert_refused(request(server, "POST", CONVERT_PATH, headers=headers, body=body), 400)
    assert recorder.calls == []


# --- One conversion at a time -------------------------------------------------------


def test_a_second_conversion_waits_for_the_first(server: WebServer, recorder: Recorder) -> None:
    recorder.release.clear()
    results: list[Response] = []
    first = threading.Thread(target=lambda: results.append(upload(server, b"first")))
    first.start()
    assert recorder.started.wait(5)
    assert_refused(upload(server, b"second"), 409)
    recorder.release.set()
    first.join(10)
    assert [response.status for response in results] == [200]
    assert recorder.calls == [b"first"]
    # Once the first is done, the next one runs.
    assert upload(server, b"third").status == 200


# --- Failures -----------------------------------------------------------------------


def test_a_refused_file_gets_the_cli_error_model(server: WebServer, recorder: Recorder) -> None:
    recorder.raises = InputUnsupportedError("not a supported input")
    response = upload(server)
    assert response.status == 422
    error = response.json()["error"]
    assert error["code"] == "INPUT_UNSUPPORTED"
    assert error["message"] == "not a supported input"
    assert error["hint"].startswith("Sugo reads PDF")
    assert upload(server).status == 422  # The server goes on.


def test_a_bug_is_logged_by_type_only(
    server: WebServer, recorder: Recorder, caplog: pytest.LogCaptureFixture
) -> None:
    recorder.raises = RuntimeError("secret document words")
    with caplog.at_level(logging.DEBUG):
        response = upload(server)
    assert (response.status, response.body) == (500, b"")
    assert "secret document words" not in caplog.text
    assert "RuntimeError" in caplog.text


def test_requests_are_never_logged(server: WebServer, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.DEBUG):
        request(server, path="/secret-name.pdf")
        upload(server)
        request(server, host="evil.example")
    assert caplog.records == []


# --- The real conversion -----------------------------------------------------------


def test_a_document_is_converted_end_to_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(CACHE_DIR_ENV, str(tmp_path / "cache"))
    payload = "<img src=x onerror=alert(1)><script>alert(2)</script>"
    document = (
        "<note><title>Hello</title><body>"
        + payload.replace("<", "&lt;").replace(">", "&gt;")
        + "</body></note>"
    ).encode()
    for server in running(converter(Settings())):
        response = upload(server, document)
    assert response.status == 200
    result = response.json()
    assert result["kind"] == "xml"
    assert result["pages"] == 1
    # The payload stays text inside a JSON string; the page shows it with textContent.
    assert payload in result["markdown"]
    assert result["text"]["result_tokens"] > 0
    assert set(result) >= {"text", "images", "rejected_by", "removed", "failed_pages"}


def test_a_refused_document_end_to_end(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(CACHE_DIR_ENV, str(tmp_path / "cache"))
    for server in running(converter(Settings())):
        response = upload(server, b"just some plain text")
    assert response.status == 422
    assert response.json()["error"]["code"] == "INPUT_UNSUPPORTED"


def test_messages_follow_the_page_language(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(CACHE_DIR_ENV, str(tmp_path / "cache"))
    body = b"just some plain text"
    for server in running(converter(Settings())):
        headers = [*api_headers(server, body), (LANGUAGE_HEADER, "it")]
        response = request(server, "POST", CONVERT_PATH, headers=headers, body=body)
    error = response.json()["error"]
    assert error["code"] == "INPUT_UNSUPPORTED"
    assert error["hint"].startswith("Sugo legge file PDF")
    # The process goes back to its own language afterwards.
    assert i18n.active_language() == "en"


def test_chunks_are_made_when_asked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(CACHE_DIR_ENV, str(tmp_path / "cache"))
    rows = "".join(
        f"<item><name>Item {n}</name><note>Line {n} of the list.</note></item>" for n in range(200)
    )
    document = f"<catalog>{rows}</catalog>".encode()
    for server in running(converter(Settings())):
        headers = [*api_headers(server, document), (CHUNKS_HEADER, "64")]
        response = request(server, "POST", CONVERT_PATH, headers=headers, body=document)
        plain = upload(server, document)
    result = response.json()
    assert result["chunk_tokens"] == 64
    chunks = [json.loads(line) for line in result["jsonl"].splitlines()]
    assert len(chunks) > 1
    assert all(chunk["schema_version"] == "1.0" for chunk in chunks)
    assert "jsonl" not in plain.json()


def test_a_conversion_in_another_language_does_not_leak(
    server: WebServer, recorder: Recorder
) -> None:
    # While a conversion speaks Italian, the page and refusals keep the server's language.
    recorder.release.clear()
    body = b"%PDF"
    headers = [*api_headers(server, body), (LANGUAGE_HEADER, "it")]
    first = threading.Thread(
        target=lambda: request(server, "POST", CONVERT_PATH, headers=headers, body=body)
    )
    first.start()
    assert recorder.started.wait(5)
    try:
        assert i18n.active_language() == "it"
        assert page_data(request(server).body)["language"] == "en"
        assert_refused(request(server, host="evil.example"), 403)
    finally:
        recorder.release.set()
        first.join(10)
    assert upload(server).status == 200
    assert recorder.options[-1].language == "en"


def test_a_refused_setting_still_gets_its_answer_with_a_large_body(
    server: WebServer, recorder: Recorder
) -> None:
    body = b"x" * 4_000_000
    headers = [*api_headers(server, body), (LANGUAGE_HEADER, "fr")]
    assert_refused(request(server, "POST", CONVERT_PATH, headers=headers, body=body), 400)
    assert recorder.calls == []
