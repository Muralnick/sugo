"""Worker processes that parse untrusted files: frames, process handling, limits.

Shared by the PDF extractor (ADR-043) and the Office and XML reader
(ADR-054). A parser of hostile files runs in its own process, which must be
assumed compromised by the file it reads. Everything it sends is data, never
code:

- each message is a frame: a 4-byte big-endian length, then that many bytes;
- frames larger than the caller's limit are refused before reading;
- callers validate every frame against strict models; pickle is never used.

Two threads move the bytes, so a stalled worker can never block Sugo: one
writes the input to the worker's stdin, the other reads frames from its
stdout into a queue that the caller waits on with a timeout.
"""

import contextlib
import os
import queue
import struct
import subprocess
import sys
import threading
from collections.abc import Iterator, Sequence
from typing import IO, Self

_LENGTH = struct.Struct(">I")
_END = object()
# Frames read ahead of the caller: enough to overlap the worker's parsing with
# Sugo's own work; more would let a long document pile up in memory.
_READ_AHEAD = 2
_JOIN_POLL_S = 0.05


class ProtocolError(RuntimeError):
    """The worker sent something that is not a valid message."""


class WorkerError(Exception):
    """The worker stalled, crashed or sent something invalid."""


def write_frame(stream: IO[bytes], payload: bytes) -> None:
    """Write one frame and flush it."""
    stream.write(_LENGTH.pack(len(payload)))
    stream.write(payload)
    stream.flush()


def read_frame(stream: IO[bytes], max_bytes: int) -> bytes | None:
    """Read one frame, or None at a clean end of stream.

    Raises:
        ProtocolError: If the frame is larger than ``max_bytes`` or cut short.
    """
    header = stream.read(_LENGTH.size)
    if not header:
        return None
    if len(header) != _LENGTH.size:
        raise ProtocolError("truncated frame header")
    (length,) = _LENGTH.unpack(header)
    if length > max_bytes:
        raise ProtocolError(f"frame of {length} bytes exceeds the limit")
    payload = stream.read(length)
    if len(payload) != length:
        raise ProtocolError("truncated frame")
    return payload


def module_command(module: str) -> tuple[str, ...]:
    """The command that runs a worker module.

    "-I": isolated mode, so the environment and the current directory cannot
    change which code the worker runs.
    """
    return (sys.executable, "-I", "-m", module)


class WorkerProcess:
    """A worker process reading one input, its frames read with a timeout."""

    def __init__(self, command: Sequence[str], data: bytes, *, max_frame_bytes: int) -> None:
        # No shell: the command is a fixed list of arguments.
        self._process = subprocess.Popen(  # noqa: S603
            list(command),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            # Parser warnings can quote the document.
            stderr=subprocess.DEVNULL,
        )
        self._max_frame_bytes = max_frame_bytes
        self._frames: queue.Queue[bytes | object] = queue.Queue(maxsize=_READ_AHEAD)
        self._writer = threading.Thread(target=self._write, args=(data,), daemon=True)
        self._reader = threading.Thread(target=self._read, daemon=True)
        self._writer.start()
        self._reader.start()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def frame(self, timeout: float) -> bytes:
        """The next frame.

        Raises:
            WorkerError: On timeout, end of output or a malformed frame.
        """
        try:
            item = self._frames.get(timeout=timeout)
        except queue.Empty:
            raise WorkerError from None
        if not isinstance(item, bytes):
            raise WorkerError
        return item

    def close(self) -> None:
        """Stop the worker if it still runs and wait for both threads."""
        if self._process.poll() is None:
            self._process.kill()
        self._process.wait()
        self._writer.join()
        # The reader may wait for room in the queue; make room until it ends.
        while self._reader.is_alive():
            with contextlib.suppress(queue.Empty):
                self._frames.get_nowait()
            self._reader.join(timeout=_JOIN_POLL_S)
        for stream in (self._process.stdin, self._process.stdout):
            if stream is not None:
                stream.close()

    def _write(self, data: bytes) -> None:
        stdin = self._process.stdin
        if stdin is None:
            return
        try:
            stdin.write(data)
            stdin.close()
        except OSError:
            pass  # The worker exited early; its output tells the reason.

    def _read(self) -> None:
        stdout = self._process.stdout
        try:
            while (
                stdout is not None
                and (frame := read_frame(stdout, self._max_frame_bytes)) is not None
            ):
                self._frames.put(frame)
        except (ProtocolError, OSError, ValueError):
            pass  # Reported to the caller as the end of the frames.
        self._frames.put(_END)


def limit_resources(memory_bytes: int) -> None:
    """In a worker: disable core dumps and cap the address space where the OS allows it.

    Core dumps would write document text to disk (ADR-031).
    """
    try:
        import resource  # POSIX only
    except ImportError:  # Windows: isolation is weaker there (ADR-031).
        return
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    # macOS refuses RLIMIT_AS on some versions; the timeouts still apply.
    with contextlib.suppress(ValueError, OSError):
        resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))


@contextlib.contextmanager
def private_stdout() -> Iterator[IO[bytes]]:
    """In a worker: a private copy of stdout for frames; file descriptor 1 goes to the null device.

    A parser may print to stdout (MuPDF's C code does on decoding errors).
    Nothing it prints can then corrupt or forge a frame.
    """
    sys.stdout.flush()
    out = os.fdopen(os.dup(1), "wb")
    null = os.open(os.devnull, os.O_WRONLY)
    os.dup2(null, 1)
    os.close(null)
    with out:
        yield out
