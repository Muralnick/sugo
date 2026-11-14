"""Download a registry model through the network gateway (ADR-036, ADR-070).

The only module of ``sugo.models`` that reaches the network. It tries the
model's sources in order; the gateway checks each address, the size and the
SHA-256, so a source can only deliver the registry's file. Offline mode
stops before the first connection. The ports call it only when the user asks
(``sugo models pull``); the MCP server never imports it (principle 10).
"""

from collections.abc import Callable
from pathlib import Path

from sugo._internal.net import NetworkError, OfflineError, Opener, download, offline_by_environment
from sugo.models.errors import DownloadFailedError, OfflineModeError
from sugo.models.registry import ModelCard, ModelFile
from sugo.models.store import download_lock, file_path, file_valid, model_dir


def is_offline(setting: bool) -> bool:
    """Whether downloads are refused: by the settings, or by ``SUGO_OFFLINE``."""
    return setting or offline_by_environment()


def pull(
    card: ModelCard,
    *,
    offline: bool,
    opener: Opener | None = None,
    progress: Callable[[int], None] | None = None,
) -> Path:
    """Make sure every file of the model is installed and valid; download those that are not.

    Args:
        progress: Called with the bytes of the model received so far.

    Returns:
        The model's folder.

    Raises:
        OfflineModeError: If offline mode is on and a file is missing.
        DownloadFailedError: If every source of a file failed.
        ModelBusyError: If another Sugo kept the download lock too long.
        StorageDirError: If the models folder is not safe to write.
    """
    with download_lock(card):
        done = 0
        for file in card.files:
            # Another Sugo may have finished it while this one waited.
            if not file_valid(card, file):
                _pull_file(card, file, offline=offline, opener=opener, progress=progress, done=done)
            done += file.size
            if progress is not None:
                progress(done)
    return model_dir(card)


def _pull_file(
    card: ModelCard,
    file: ModelFile,
    *,
    offline: bool,
    opener: Opener | None,
    progress: Callable[[int], None] | None,
    done: int,
) -> None:
    destination = file_path(card, file)
    # A damaged copy is replaced; the gateway writes .part, then renames.
    destination.unlink(missing_ok=True)
    failures: list[tuple[str, str]] = []
    for source in file.sources:
        try:
            download(
                source.url,
                destination,
                size=file.size,
                sha256=file.sha256,
                offline=offline,
                opener=opener,
                progress=None if progress is None else lambda got: progress(done + got),
            )
        except OfflineError:
            raise OfflineModeError("offline mode is on") from None
        except NetworkError as error:
            failures.append((source.name, error.reason))
            continue
        return
    raise DownloadFailedError(failures)
