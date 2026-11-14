"""Network gateway: the only path to the internet, with offline mode, address checks and logging.

Every outbound connection Sugo makes goes through ``download`` (ADR-036,
ADR-070), and only model downloads call it today. It refuses before
connecting when Sugo is offline, and otherwise allows only:

- HTTPS, with the system's certificate store, also after a redirect;
- hosts on a fixed list, at most five redirects;
- public addresses, when it connects directly: a name that resolves to a
  private, loopback or link-local address is refused (SSRF). Through a proxy
  set in the standard environment variables, as companies need, the proxy
  connects and decides;
- as many bytes as the caller expects, never more.

The file is written next to its destination as ``.part``, resumed with a
``Range`` request after an interruption, and gets its final name only once
its size and SHA-256 match (ADR-013). The log names the host, the size and
the outcome, never a file name of the user's (principle 11).

Residual risk, left to the host list: the address is checked when the
request is made, and the connection resolves the name again, so a host on
the list whose DNS turned hostile could still point it elsewhere.
"""

import hashlib
import ipaddress
import logging
import os
import socket
import ssl
import stat
import urllib.error
import urllib.parse
from collections.abc import Callable
from http import HTTPStatus

# The gateway is the only module allowed these imports (ADR-036).
from http.client import HTTPException, HTTPMessage, HTTPResponse  # noqa: TID251
from pathlib import Path
from typing import IO, BinaryIO, Protocol
from urllib.request import (  # noqa: TID251
    BaseHandler,
    HTTPDefaultErrorHandler,
    HTTPErrorProcessor,
    HTTPRedirectHandler,
    HTTPSHandler,
    OpenerDirector,
    ProxyHandler,
    Request,
    UnknownHandler,
)

# Refuses every download when set to a true value, whatever the settings say.
OFFLINE_ENV = "SUGO_OFFLINE"

# Hosts the gateway may connect to, and the domains whose subdomains it may.
ALLOWED_HOSTS = frozenset(
    {
        "github.com",
        "objects.githubusercontent.com",
        "release-assets.githubusercontent.com",
        "www.modelscope.cn",
    }
)
ALLOWED_DOMAINS = ("modelscope.cn",)
MAX_REDIRECTS = 5
TIMEOUT_S = 30.0
CHUNK_BYTES = 1024 * 1024

_log = logging.getLogger(__name__)
_TRUE = frozenset({"1", "true", "yes", "on"})


class NetworkError(Exception):
    """A download did not happen or did not complete; ``reason`` says why, in English."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class OfflineError(NetworkError):
    """Sugo is in offline mode: nothing was sent."""


class RefusedError(NetworkError):
    """The address is not one the gateway may reach: nothing was sent to it."""


class TransferError(NetworkError):
    """The server failed, or sent something other than the expected file."""


class Response(Protocol):
    """What the gateway reads from an HTTP response."""

    status: int

    def getheader(self, name: str, default: str | None = None) -> str | None: ...

    def read(self, size: int = -1) -> bytes: ...

    def close(self) -> None: ...


Opener = Callable[[Request], Response]


def offline_by_environment() -> bool:
    """Whether ``SUGO_OFFLINE`` turns offline mode on."""
    return os.environ.get(OFFLINE_ENV, "").strip().lower() in _TRUE


def download(
    url: str,
    destination: Path,
    *,
    size: int,
    sha256: str,
    offline: bool,
    opener: Opener | None = None,
    progress: Callable[[int], None] | None = None,
) -> None:
    """Fetch ``url`` into ``destination``, checked against ``size`` and ``sha256``.

    Args:
        url: An HTTPS address on an allowed host.
        destination: Where the file goes; ``<destination>.part`` holds it meanwhile.
        size: The exact size in bytes; a larger body is cut off and refused.
        sha256: The expected SHA-256, lower-case hex.
        offline: Offline mode from the settings; the environment can also set it.
        opener: Makes the request; tests pass a fake, Sugo passes None.
        progress: Called with the bytes received so far.

    Raises:
        OfflineError: In offline mode, before any connection.
        RefusedError: If the address, or a redirect, is not allowed.
        TransferError: If the transfer fails or the file is not the expected one;
            a wrong file is deleted, an interrupted one kept to resume.
    """
    if offline or offline_by_environment():
        raise OfflineError("offline mode is on")
    check_url(url)
    host = urllib.parse.urlsplit(url).hostname or ""
    part = destination.with_name(destination.name + ".part")
    try:
        _fetch(url, part, size=size, opener=opener or _default_opener(), progress=progress)
        _verify(part, size=size, sha256=sha256)
    except NetworkError as error:
        _log.info("download from %s failed: %s", host, error.reason)
        raise
    os.replace(part, destination)
    _log.info("download from %s: %d bytes, verified", host, size)


def check_url(url: str) -> None:
    """Refuse an address that is not HTTPS on an allowed host.

    Raises:
        RefusedError: If it is not.
    """
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https":
        raise RefusedError("only https is allowed")
    if parts.username or parts.password:
        raise RefusedError("credentials in the address are not allowed")
    host = (parts.hostname or "").rstrip(".").lower()
    allowed = host in ALLOWED_HOSTS or any(host.endswith("." + d) for d in ALLOWED_DOMAINS)
    if not allowed:
        raise RefusedError("host is not on the allowed list")
    if parts.port not in (None, 443):
        raise RefusedError("only the standard https port is allowed")


def check_addresses(host: str, resolve: Callable[[str], list[str]] | None = None) -> None:
    """Refuse a host name that resolves to an address that is not public.

    Raises:
        RefusedError: If any address is private, loopback, link-local,
            multicast, reserved or unspecified, or the name does not resolve.
    """
    try:
        addresses = (resolve or _resolve)(host)
    except OSError:
        raise TransferError("host name did not resolve") from None
    if not addresses:
        raise TransferError("host name did not resolve")
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global or ip.is_multicast:
            raise RefusedError("host resolves to an address that is not public")


def _resolve(host: str) -> list[str]:
    infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    # The scope id of an IPv6 address ("%eth0") is not part of the address.
    return [str(info[4][0]).split("%")[0] for info in infos]


def _fetch(
    url: str,
    part: Path,
    *,
    size: int,
    opener: Opener,
    progress: Callable[[int], None] | None,
) -> None:
    """Write the body to ``part``, resuming what an earlier run left there."""
    have = _existing_size(part, size)
    # The scheme and host were checked by check_url: https only.
    request = Request(url, headers={"User-Agent": "sugo", "Accept": "*/*"})  # noqa: S310
    if have:
        request.add_header("Range", f"bytes={have}-")
    try:
        response = opener(request)
    except NetworkError:
        raise
    except urllib.error.HTTPError as error:
        error.close()
        raise TransferError(f"server answered {error.code}") from None
    except (urllib.error.URLError, OSError, HTTPException) as error:
        raise TransferError(f"connection failed: {type(error).__name__}") from None
    try:
        partial = response.status == HTTPStatus.PARTIAL_CONTENT
        resumed = have > 0 and partial and _range_start(response) == have
        if response.status not in (HTTPStatus.OK, HTTPStatus.PARTIAL_CONTENT) or (
            partial and not resumed
        ):
            raise TransferError(f"server answered {response.status}")
        if not resumed:
            # A server that ignores Range sends the whole file again.
            have = 0
        with part.open("ab" if resumed else "wb") as file:
            _copy(response, file, have=have, size=size, progress=progress)
    except (OSError, HTTPException) as error:
        raise TransferError(f"transfer interrupted: {type(error).__name__}") from None
    finally:
        response.close()


def _copy(
    response: Response,
    file: BinaryIO,
    *,
    have: int,
    size: int,
    progress: Callable[[int], None] | None,
) -> None:
    while chunk := response.read(CHUNK_BYTES):
        have += len(chunk)
        if have > size:
            file.truncate(0)
            raise TransferError("server sent more bytes than expected")
        file.write(chunk)
        if progress is not None:
            progress(have)
    if have != size:
        raise TransferError("transfer ended before the whole file arrived")


def _verify(part: Path, *, size: int, sha256: str) -> None:
    digest = hashlib.sha256()
    with part.open("rb") as file:
        while chunk := file.read(CHUNK_BYTES):
            digest.update(chunk)
    if part.stat().st_size != size or digest.hexdigest() != sha256:
        part.unlink(missing_ok=True)
        raise TransferError("file does not match its SHA-256")


def _existing_size(part: Path, size: int) -> int:
    """What an interrupted run left; anything odd is started over."""
    try:
        info = part.lstat()
    except FileNotFoundError:
        return 0
    # A link is removed, never followed: writing through it would write elsewhere.
    if not stat.S_ISREG(info.st_mode) or info.st_size >= size:
        part.unlink()
        return 0
    return info.st_size


def _range_start(response: Response) -> int | None:
    """The first byte of a ``Content-Range: bytes a-b/n`` answer."""
    value = response.getheader("Content-Range") or ""
    unit, _, rest = value.partition(" ")
    start, _, _ = rest.partition("-")
    if unit != "bytes" or not start.isdigit():
        return None
    return int(start)


class _CheckedRedirects(HTTPRedirectHandler):
    """Follows a redirect only to an allowed HTTPS address, at most ``MAX_REDIRECTS`` times."""

    max_redirections = MAX_REDIRECTS

    def redirect_request(
        self,
        req: Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: HTTPMessage,
        newurl: str,
    ) -> Request | None:
        check_url(newurl)
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None and req.has_header("Range"):
            # urllib drops most headers on a redirect; the resume must survive it.
            new.add_unredirected_header("Range", str(req.get_header("Range")))
        return new


class _CheckedHttps(HTTPSHandler):
    """Checks the addresses of a host before connecting to it directly."""

    def __init__(self) -> None:
        super().__init__(context=ssl.create_default_context())

    def https_open(self, req: Request) -> HTTPResponse:
        host = req.host.rsplit(":", 1)[0].strip("[]")
        # Through a proxy, urllib sets the proxy as the host and the proxy
        # connects to the server: only a direct connection is checked here.
        if not getattr(req, "_tunnel_host", None):
            check_addresses(host)
        return super().https_open(req)


def _default_opener() -> Opener:
    handlers: list[BaseHandler] = [
        ProxyHandler(),
        _CheckedRedirects(),
        _CheckedHttps(),
    ]
    built = OpenerDirector()
    for handler in (
        *handlers,
        HTTPDefaultErrorHandler(),
        HTTPErrorProcessor(),
        UnknownHandler(),
    ):
        built.add_handler(handler)

    def open_url(request: Request) -> Response:
        response: Response = built.open(request, timeout=TIMEOUT_S)
        return response

    return open_url
