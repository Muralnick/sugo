"""Tests for the network gateway: allowed addresses, offline mode, resume, checks (ADR-070).

No test reaches the internet: a fake opener stands in for the server, and
the conftest makes the real one fail.
"""

import hashlib
import os
import sys
from email.message import Message
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request  # noqa: TID251 - building requests, as the gateway does

import pytest

from sugo._internal import net
from sugo._internal.net import (
    OfflineError,
    RefusedError,
    TransferError,
    check_addresses,
    check_url,
    download,
)

BODY = bytes(range(256)) * 400  # 102 400 bytes
SHA = hashlib.sha256(BODY).hexdigest()
URL = "https://github.com/Muralnick/sugo/releases/download/models-1/model.onnx"


class FakeResponse:
    def __init__(self, status: int, body: bytes, headers: dict[str, str] | None = None) -> None:
        self.status = status
        self._body = BytesIO(body)
        self._headers = headers or {}
        self.closed = False

    def getheader(self, name: str, default: str | None = None) -> str | None:
        return self._headers.get(name, default)

    def read(self, size: int = -1) -> bytes:
        return self._body.read(size)

    def close(self) -> None:
        self.closed = True


class FakeServer:
    """Serves ``body``, honouring Range unless told not to; records the requests."""

    def __init__(self, body: bytes = BODY, *, ranges: bool = True, status: int = 200) -> None:
        self.body = body
        self.ranges = ranges
        self.status = status
        self.requests: list[Request] = []

    def __call__(self, request: Request) -> FakeResponse:
        self.requests.append(request)
        if self.status != 200:
            raise HTTPError(request.full_url, self.status, "error", Message(), None)
        wanted = request.get_header("Range")
        if wanted and self.ranges:
            start = int(wanted.removeprefix("bytes=").rstrip("-"))
            headers = {"Content-Range": f"bytes {start}-{len(self.body) - 1}/{len(self.body)}"}
            return FakeResponse(206, self.body[start:], headers)
        return FakeResponse(200, self.body)


def fetch(destination: Path, server: FakeServer, **changes: object) -> None:
    arguments: dict[str, object] = {"size": len(BODY), "sha256": SHA, "offline": False}
    arguments.update(changes)
    download(URL, destination, opener=server, **arguments)  # type: ignore[arg-type]


class TestAddresses:
    @pytest.mark.parametrize(
        "url",
        [
            URL,
            "https://objects.githubusercontent.com/x",
            "https://release-assets.githubusercontent.com/x",
            "https://www.modelscope.cn/models/x",
            "https://cdn-lfs-cn-1.modelscope.cn/prod/x?auth_key=1",
            "https://GitHub.com./x",
            "https://huggingface.co/org/model/resolve/abc/model.safetensors",
            "https://us.aws.cdn.hf.co/xet-bridge-us/x",
        ],
    )
    def test_allowed_https_addresses(self, url: str) -> None:
        check_url(url)

    @pytest.mark.parametrize(
        "url",
        [
            "http://github.com/x",  # not https
            "file:///etc/passwd",
            "https://example.com/x",  # not on the list
            "https://github.com.evil.example/x",
            "https://evilmodelscope.cn/x",  # not a subdomain
            "https://evilhf.co/x",
            "https://huggingface.co.evil.example/x",
            "https://user:pw@github.com/x",
            "https://github.com:8443/x",
        ],
    )
    def test_other_addresses_are_refused(self, url: str) -> None:
        with pytest.raises(RefusedError):
            check_url(url)

    @pytest.mark.parametrize(
        "addresses",
        [
            ["10.0.0.5"],
            ["127.0.0.1"],
            ["169.254.169.254"],
            ["::1"],
            ["fd00::1"],
            ["8.8.8.8", "192.168.1.1"],
        ],
    )
    def test_names_resolving_to_non_public_addresses_are_refused(
        self, addresses: list[str]
    ) -> None:
        with pytest.raises(RefusedError):
            check_addresses("github.com", resolve=lambda _host: addresses)

    def test_public_addresses_pass(self) -> None:
        check_addresses("github.com", resolve=lambda _host: ["140.82.121.4", "2606:50c0::1"])

    def test_a_name_that_does_not_resolve_is_a_transfer_error(self) -> None:
        def fail(_host: str) -> list[str]:
            raise OSError("no such host")

        with pytest.raises(TransferError):
            check_addresses("github.com", resolve=fail)


class TestRedirects:
    def _redirect(self, target: str) -> Request | None:
        handler = net._CheckedRedirects()
        request = Request(URL, headers={"Range": "bytes=10-"})
        return handler.redirect_request(request, BytesIO(), 302, "Found", Message(), target)  # type: ignore[arg-type]

    def test_a_redirect_to_an_allowed_host_keeps_the_range(self) -> None:
        new = self._redirect("https://objects.githubusercontent.com/file")
        assert new is not None
        assert new.get_header("Range") == "bytes=10-"

    @pytest.mark.parametrize(
        "target", ["http://objects.githubusercontent.com/file", "https://example.com/file"]
    )
    def test_a_redirect_elsewhere_is_refused(self, target: str) -> None:
        with pytest.raises(RefusedError):
            self._redirect(target)

    def test_at_most_five_redirects(self) -> None:
        assert net._CheckedRedirects.max_redirections == net.MAX_REDIRECTS == 5


class TestDownload:
    def test_a_verified_file_gets_its_name(self, tmp_path: Path) -> None:
        seen: list[int] = []
        fetch(tmp_path / "model.onnx", FakeServer(), progress=seen.append)
        assert (tmp_path / "model.onnx").read_bytes() == BODY
        assert not (tmp_path / "model.onnx.part").exists()
        assert seen[-1] == len(BODY)

    def test_offline_mode_sends_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        server = FakeServer()
        with pytest.raises(OfflineError):
            fetch(tmp_path / "m", server, offline=True)
        monkeypatch.setenv(net.OFFLINE_ENV, "1")
        with pytest.raises(OfflineError):
            fetch(tmp_path / "m", server)
        assert server.requests == []

    def test_a_refused_address_sends_nothing(self, tmp_path: Path) -> None:
        server = FakeServer()
        with pytest.raises(RefusedError):
            download(
                "http://github.com/x",
                tmp_path / "m",
                size=1,
                sha256=SHA,
                offline=False,
                opener=server,
            )
        assert server.requests == []

    def test_an_interrupted_download_resumes(self, tmp_path: Path) -> None:
        (tmp_path / "m.part").write_bytes(BODY[:1000])
        server = FakeServer()
        fetch(tmp_path / "m", server)
        assert server.requests[0].get_header("Range") == "bytes=1000-"
        assert (tmp_path / "m").read_bytes() == BODY

    def test_a_server_ignoring_the_range_starts_over(self, tmp_path: Path) -> None:
        (tmp_path / "m.part").write_bytes(b"x" * 1000)
        fetch(tmp_path / "m", FakeServer(ranges=False))
        assert (tmp_path / "m").read_bytes() == BODY

    def test_a_wrong_file_is_deleted(self, tmp_path: Path) -> None:
        other = bytes(len(BODY))
        with pytest.raises(TransferError, match="SHA-256"):
            fetch(tmp_path / "m", FakeServer(other))
        assert not (tmp_path / "m").exists()
        assert not (tmp_path / "m.part").exists()

    def test_more_bytes_than_expected_are_refused(self, tmp_path: Path) -> None:
        with pytest.raises(TransferError, match="more bytes"):
            fetch(tmp_path / "m", FakeServer(BODY + b"extra"))
        assert not (tmp_path / "m").exists()

    def test_a_short_body_is_kept_to_resume(self, tmp_path: Path) -> None:
        with pytest.raises(TransferError, match="before the whole file"):
            fetch(tmp_path / "m", FakeServer(BODY[:500]))
        assert (tmp_path / "m.part").read_bytes() == BODY[:500]
        assert not (tmp_path / "m").exists()

    def test_server_errors_and_broken_connections(self, tmp_path: Path) -> None:
        with pytest.raises(TransferError, match="404"):
            fetch(tmp_path / "m", FakeServer(status=404))

        def broken(_request: Request) -> FakeResponse:
            raise URLError("refused")

        with pytest.raises(TransferError, match="connection failed"):
            download(URL, tmp_path / "m", size=1, sha256=SHA, offline=False, opener=broken)

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX symbolic links")
    def test_a_planted_part_link_is_removed_not_followed(self, tmp_path: Path) -> None:
        target = tmp_path / "elsewhere"
        os.symlink(target, tmp_path / "m.part")
        fetch(tmp_path / "m", FakeServer())
        assert not target.exists()
        assert (tmp_path / "m").read_bytes() == BODY

    def test_the_log_names_the_host_never_the_file(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        caplog.set_level("INFO", logger="sugo._internal.net")
        fetch(tmp_path / "secret-name", FakeServer())
        assert "github.com" in caplog.text
        assert "secret-name" not in caplog.text
