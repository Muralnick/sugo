"""Tests for the worker protocol: only well-formed, bounded messages get through."""

import io
import struct

import pytest

from sugo.core.constants import PDF_MAX_MESSAGE_BYTES, PDF_OCR_MAX_PIXELS
from sugo.core.models import BBox
from sugo.extractors.pymupdf.protocol import (
    Message,
    NativeLine,
    NativePage,
    Opened,
    PageBox,
    ProtocolError,
    parse_message,
    read_frame,
    write_message,
)


def test_messages_round_trip() -> None:
    line = NativeLine(
        text="  indented",
        bbox=BBox(x0=0.1, y0=0.1, x1=0.5, y1=0.12),
        font_size=11.0,
        bold=False,
        monospace=True,
        hidden=False,
    )
    messages: list[Message] = [
        Opened(pages=(PageBox(width=595.0, height=842.0, rotation=90),)),
        NativePage(index=0, lines=(line,)),
    ]
    stream = io.BytesIO()
    for message in messages:
        write_message(stream, message)
    stream.seek(0)
    frames = [read_frame(stream), read_frame(stream), read_frame(stream)]
    assert frames[2] is None
    assert [parse_message(frame) for frame in frames[:2] if frame is not None] == messages


def test_oversized_frame_is_refused_before_reading() -> None:
    stream = io.BytesIO(struct.pack(">I", PDF_MAX_MESSAGE_BYTES + 1))
    with pytest.raises(ProtocolError, match="exceeds"):
        read_frame(stream)


@pytest.mark.parametrize("data", [b"\x00\x00", struct.pack(">I", 10) + b"short"])
def test_truncated_frame_is_refused(data: bytes) -> None:
    with pytest.raises(ProtocolError, match="truncated"):
        read_frame(io.BytesIO(data))


@pytest.mark.parametrize(
    "payload",
    [
        b"not json",
        b'{"kind": "opened", "pages": [], "extra": 1}',
        b'{"kind": "exec", "code": "x"}',
        b'{"kind": "page_failed", "index": -1}',
        b'{"kind": "refused", "code": "OTHER", "message": "x"}',
        b'{"kind": "native", "index": 0, "lines": [{"text": "", "bbox": null, '
        b'"font_size": 1, "bold": false, "monospace": false, "hidden": false}]}',
    ],
)
def test_invalid_messages_are_refused(payload: bytes) -> None:
    with pytest.raises(ProtocolError, match="invalid message"):
        parse_message(payload)


def test_error_does_not_quote_the_payload() -> None:
    # The payload carries document text, which must not reach logs (principle 11).
    with pytest.raises(ProtocolError) as caught:
        parse_message(b'{"kind": "secret clause"}')
    assert "secret" not in str(caught.value)


def test_scan_beyond_the_pixel_limit_is_refused() -> None:
    side = int(PDF_OCR_MAX_PIXELS**0.5) + 1
    payload = (
        b'{"kind": "scan", "index": 0, "pixel_width": %d, "pixel_height": %d, '
        b'"hidden_lines": []}' % (side, side)
    )
    with pytest.raises(ProtocolError, match="pixel limit"):
        parse_message(payload)
