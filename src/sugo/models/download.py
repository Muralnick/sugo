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
from sugo.models.errors import DownloadFailedError, ModelInvalidError, OfflineModeError
from sugo.models.registry import ModelCard
from sugo.models.store import download_lock, find, model_path, verify


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
    """Make sure the model is installed and valid; download it if it is not.

    Returns:
        The path of the verified file.

    Raises:
        OfflineModeError: If offline mode is on and the model is missing.
        DownloadFailedError: If every source failed.
        ModelBusyError: If another Sugo kept the download lock too long.
        StorageDirError: If the models folder is not safe to write.
    """
    with download_lock(card):
        # Another Sugo may have finished it while this one waited.
        installed = find(card)
        if installed is not None:
            try:
                return verify(installed)
            except ModelInvalidError:
                # A damaged copy is replaced.
                installed.path.unlink(missing_ok=True)
        failures: list[tuple[str, str]] = []
        for source in card.sources:
            try:
                download(
                    source.url,
                    model_path(card),
                    size=card.size,
                    sha256=card.sha256,
                    offline=offline,
                    opener=opener,
                    progress=progress,
                )
            except OfflineError:
                raise OfflineModeError("offline mode is on") from None
            except NetworkError as error:
                failures.append((source.name, error.reason))
                continue
            return model_path(card)
        raise DownloadFailedError(failures)
