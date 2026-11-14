"""The models Sugo can download, fixed in the code (ADR-013, ADR-070).

Each record pins one file: its size, its SHA-256, its licence and where to
fetch it. Only these files can be downloaded or installed, and only in a safe
format (ONNX, safetensors, GGUF), which never runs code when loaded. A new
model or a new version is a reviewed change to this module, never a list
fetched at run time. Sources are tried in order; the hash is fixed, so every
source can only deliver the same file.
"""

from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

from sugo.models.errors import UnknownModelError

Format = Literal["onnx", "safetensors", "gguf"]


@dataclass(frozen=True)
class Source:
    """One place a model file can be fetched from."""

    name: str
    url: str


@dataclass(frozen=True)
class ModelCard:
    """One downloadable model file."""

    id: str
    task: str
    languages: tuple[str, ...]
    format: Format
    file_name: str
    size: int
    sha256: str
    licence: str
    notice: str
    revision: str
    sources: tuple[Source, ...]

    @property
    def size_mb(self) -> int:
        """The size in whole megabytes, for error details."""
        return round(self.size / 1_000_000)

    @property
    def suffix(self) -> str:
        """The file extension of the format."""
        return "." + self.format


_KOREAN_FILE = "korean_PP-OCRv5_rec_mobile.onnx"

REGISTRY = MappingProxyType(
    {
        "ocr-korean": ModelCard(
            id="ocr-korean",
            task="ocr-recognition",
            languages=("ko",),
            format="onnx",
            file_name=_KOREAN_FILE,
            size=13_488_748,
            sha256="cd6e2ea50f6943ca7271eb8c56a877a5a90720b7047fe9c41a2e541a25773c9b",
            licence="Apache-2.0",
            notice=(
                "PP-OCRv5 Korean recognition model by PaddlePaddle (PaddleOCR), "
                "converted to ONNX by RapidAI (RapidOCR 3.10.0)."
            ),
            revision="RapidAI/RapidOCR v3.10.0",
            sources=(
                # A copy in this repository's releases (maintainer decision, ADR-070).
                Source(
                    "GitHub",
                    f"https://github.com/Muralnick/sugo/releases/download/models-1/{_KOREAN_FILE}",
                ),
                Source(
                    "ModelScope",
                    "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.10.0/"
                    f"onnx/PP-OCRv5/rec/{_KOREAN_FILE}",
                ),
            ),
        ),
    }
)


def card(model_id: str) -> ModelCard:
    """The registry record of ``model_id``.

    Raises:
        UnknownModelError: If there is none.
    """
    try:
        return REGISTRY[model_id]
    except KeyError:
        raise UnknownModelError(model_id) from None
