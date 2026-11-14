"""What can go wrong with a model, as exceptions with stable codes (ADR-070).

Apart from the download itself, so the ports can tell these errors apart
without importing the module that reaches the network: the MCP server never
does (ADR-049). Messages are English and name only the model, never a file
of the user's; the ports turn them into translated messages.
"""

from typing import ClassVar


class UnknownModelError(ValueError):
    """No model with this id is in the registry."""

    code: ClassVar[str] = "MODEL_UNKNOWN"


class ModelInvalidError(RuntimeError):
    """An installed model does not match its SHA-256: changed or damaged on disk."""

    code: ClassVar[str] = "MODEL_INVALID"


class ModelMissingError(RuntimeError):
    """A model that is needed, or asked for, is not installed."""

    code: ClassVar[str] = "MODEL_MISSING"


class BundleInvalidError(ValueError):
    """An offline bundle is not one Sugo wrote, or holds something it does not trust."""

    code: ClassVar[str] = "BUNDLE_INVALID"


class ModelBusyError(RuntimeError):
    """Another Sugo is downloading the same model and did not finish in time."""

    code: ClassVar[str] = "MODEL_BUSY"


class OfflineModeError(RuntimeError):
    """Offline mode is on: nothing was downloaded."""

    code: ClassVar[str] = "OFFLINE"


class DownloadFailedError(RuntimeError):
    """No source delivered the model; ``failures`` says why for each, in English."""

    code: ClassVar[str] = "DOWNLOAD_FAILED"

    def __init__(self, failures: list[tuple[str, str]]) -> None:
        super().__init__("; ".join(f"{name}: {reason}" for name, reason in failures))
        self.failures = failures
