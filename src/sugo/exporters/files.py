"""Write output files atomically: a reader sees the old file or the new one, never half.

The text goes to a temporary file in the same folder, is flushed to disk,
then renamed over the target (ARCHITECTURE §10, atomic writes). A crash or a
full disk leaves the previous output intact. The temporary name is short and
fixed in shape, so long document names never hit Windows path limits.

New files are created readable only by their owner, like every file Sugo
writes with document text (ADR-047).
"""

import os
import tempfile
from collections.abc import Iterable
from pathlib import Path


def write_text_atomic(path: Path, parts: Iterable[str]) -> None:
    """Write ``parts``, UTF-8 with ``\\n`` line ends, to ``path`` in one step.

    Raises:
        OSError: If the folder does not exist or cannot be written; the
            target is then left as it was.
    """
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".sugo-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as file:
            for part in parts:
                file.write(part)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
