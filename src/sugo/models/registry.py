"""The models Sugo can download, fixed in the code (ADR-013, ADR-070, ADR-071).

Each record pins every file of one model: its path, size, SHA-256 and where
to fetch it. Only these files can be downloaded or installed, and the
weights only in a safe format (ONNX, safetensors, GGUF), which never runs
code when loaded; the small configuration files beside them are JSON. A new
model or a new version is a reviewed change to this module, never a list
fetched at run time. Sources are tried in order; the hash is fixed, so every
source can only deliver the same file.

A model's files live in ``<models dir>/<folder>/<path>``. Docling's two
models share the folder ``docling`` and keep the layout Docling expects, so
that folder is Docling's ``artifacts_path`` (ADR-071).
"""

from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

from sugo.models.errors import UnknownModelError

Format = Literal["onnx", "safetensors", "gguf"]
# Weights in a safe format, and the configuration files Docling reads with them.
ALLOWED_SUFFIXES = (".onnx", ".safetensors", ".gguf", ".json")


@dataclass(frozen=True)
class Source:
    """One place a model file can be fetched from."""

    name: str
    url: str


@dataclass(frozen=True)
class ModelFile:
    """One file of a model: where it goes, what it is, where it comes from."""

    path: str
    size: int
    sha256: str
    sources: tuple[Source, ...]

    @property
    def name(self) -> str:
        """The file name, without its folders."""
        return self.path.rsplit("/", 1)[-1]


@dataclass(frozen=True)
class ModelCard:
    """One downloadable model: one or more files."""

    id: str
    task: str
    languages: tuple[str, ...]
    level: str
    format: Format
    folder: str
    files: tuple[ModelFile, ...]
    licence: str
    notice: str
    revision: str

    @property
    def size(self) -> int:
        """The size of all its files, in bytes."""
        return sum(file.size for file in self.files)

    @property
    def size_mb(self) -> int:
        """The size in whole megabytes, for error details."""
        return round(self.size / 1_000_000)

    @property
    def sources(self) -> tuple[str, ...]:
        """The names of the places its files come from, in order."""
        return tuple(dict.fromkeys(s.name for file in self.files for s in file.sources))


def _huggingface(repository: str, commit: str, path: str) -> Source:
    return Source("Hugging Face", f"https://huggingface.co/{repository}/resolve/{commit}/{path}")


_KOREAN_FILE = "korean_PP-OCRv5_rec_mobile.onnx"
_LAYOUT_REPO = "docling-project/docling-layout-heron"
_LAYOUT_COMMIT = "8f39ad3c0b4c58e9c2d2c84a38465abf757272d8"
_LAYOUT_DIR = "docling-project--docling-layout-heron"
_TABLES_REPO = "docling-project/docling-models"
_TABLES_COMMIT = "2199320848bb9a8a519d22e4b528185a4f9a6f64"
_TABLES_DIR = "docling-project--docling-models/model_artifacts/tableformer/accurate"

REGISTRY = MappingProxyType(
    {
        "ocr-korean": ModelCard(
            id="ocr-korean",
            task="ocr-recognition",
            languages=("ko",),
            level="lite",
            format="onnx",
            folder="ocr-korean",
            files=(
                ModelFile(
                    path=_KOREAN_FILE,
                    size=13_488_748,
                    sha256="cd6e2ea50f6943ca7271eb8c56a877a5a90720b7047fe9c41a2e541a25773c9b",
                    sources=(
                        # A copy in this repository's releases (maintainer decision, ADR-070).
                        Source(
                            "GitHub",
                            "https://github.com/Muralnick/sugo/releases/download/models-1/"
                            + _KOREAN_FILE,
                        ),
                        Source(
                            "ModelScope",
                            "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.10.0/"
                            f"onnx/PP-OCRv5/rec/{_KOREAN_FILE}",
                        ),
                    ),
                ),
            ),
            licence="Apache-2.0",
            notice=(
                "PP-OCRv5 Korean recognition model by PaddlePaddle (PaddleOCR), "
                "converted to ONNX by RapidAI (RapidOCR 3.10.0)."
            ),
            revision="RapidAI/RapidOCR v3.10.0",
        ),
        "layout-docling": ModelCard(
            id="layout-docling",
            task="layout",
            languages=(),
            level="normal",
            format="safetensors",
            folder="docling",
            files=tuple(
                ModelFile(
                    path=f"{_LAYOUT_DIR}/{name}",
                    size=size,
                    sha256=sha256,
                    sources=(_huggingface(_LAYOUT_REPO, _LAYOUT_COMMIT, name),),
                )
                for name, size, sha256 in (
                    (
                        "model.safetensors",
                        171_658_996,
                        "00333a43451945aaf89db8ca9c0a17e75d1537c17db60fdb91aa95f4c7929e0c",
                    ),
                    (
                        "config.json",
                        3268,
                        "fdea30805ce2f5666b147fca941dcdd27ad468e27d6ed21902207d3da056a97d",
                    ),
                    (
                        "preprocessor_config.json",
                        444,
                        "cd38cd59999e7a95d68e487fbe5132df3d4e5c32a0836add57e6126ba0c4eaf1",
                    ),
                )
            ),
            licence="Apache-2.0",
            notice="Docling layout model (Heron) by the Docling project.",
            revision=f"{_LAYOUT_REPO}@{_LAYOUT_COMMIT}",
        ),
        "tables-docling": ModelCard(
            id="tables-docling",
            task="table-structure",
            languages=(),
            level="normal",
            format="safetensors",
            folder="docling",
            files=tuple(
                ModelFile(
                    path=f"{_TABLES_DIR}/{name}",
                    size=size,
                    sha256=sha256,
                    sources=(
                        _huggingface(
                            _TABLES_REPO,
                            _TABLES_COMMIT,
                            f"model_artifacts/tableformer/accurate/{name}",
                        ),
                    ),
                )
                for name, size, sha256 in (
                    (
                        "tableformer_accurate.safetensors",
                        212_758_388,
                        "2a7d6c924b3cd12fb99a09280ca9c33a89c5d60b93253617d2e088c1a40374d9",
                    ),
                    (
                        "tm_config.json",
                        7060,
                        "984e122ceb8ccf84d84c9d2882f6f2302a44b4f1e577babd6289892c36f3cffd",
                    ),
                )
            ),
            licence="CDLA-Permissive-2.0 / Apache-2.0",
            notice="Docling table structure model (TableFormer, accurate) by the Docling project.",
            revision=f"{_TABLES_REPO}@{_TABLES_COMMIT}",
        ),
    }
)

# Names that stand for several models: `sugo models pull normal` (ARCHITECTURE §12).
GROUPS = MappingProxyType({"normal": ("layout-docling", "tables-docling")})


def card(model_id: str) -> ModelCard:
    """The registry record of ``model_id``.

    Raises:
        UnknownModelError: If there is none.
    """
    try:
        return REGISTRY[model_id]
    except KeyError:
        raise UnknownModelError(model_id) from None


def cards(name: str) -> tuple[ModelCard, ...]:
    """The models a name stands for: a group such as ``normal``, or one model.

    Raises:
        UnknownModelError: If it is neither.
    """
    if name in GROUPS:
        return tuple(card(model_id) for model_id in GROUPS[name])
    return (card(name),)
