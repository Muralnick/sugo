"""Run OCR on a prepared image and return text lines with normalised boxes.

Wraps RapidOCR (ADR-004, ADR-039) so the rest of Sugo never touches it:

- models are given by explicit path and SHA-256 checked before loading, so
  RapidOCR never downloads anything and an altered file is refused;
- RapidOCR's own confidence filter is disabled, because it drops lines
  silently; lines below Sugo's threshold are kept as illegible lines without
  text (principles 3 and 4);
- RapidOCR's logging is silenced: at its default level it logs file paths
  (principle 11).

Lines come back in detector order; reading order and grouping into blocks are
the job of the layout module.
"""

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import rapidocr
from rapidocr import RapidOCR
from rapidocr.utils.output import RapidOCROutput

from sugo.core.constants import (
    OCR_DETECTION_MAX_SIDE,
    OCR_MIN_CONFIDENCE,
    PPOCRV6_DET_SMALL_SHA256,
    PPOCRV6_REC_SMALL_SHA256,
)
from sugo.core.models import BBox
from sugo.extractors.image.preprocess import PreparedImage
from sugo.i18n import gettext as _

ENGINE_NAME = "rapidocr-ppocrv6-small"
_HASH_CHUNK_BYTES = 1024 * 1024


class ModelIntegrityError(RuntimeError):
    """A model file does not match its pinned SHA-256; it was altered or corrupted."""


@dataclass(frozen=True)
class OcrModel:
    """A model file and the hash it must have."""

    path: Path
    sha256: str

    def verify(self) -> None:
        """Check the file against its pinned hash.

        Raises:
            ModelIntegrityError: If the hash does not match.
            OSError: If the file cannot be read.
        """
        digest = hashlib.sha256()
        with self.path.open("rb") as file:
            while chunk := file.read(_HASH_CHUNK_BYTES):
                digest.update(chunk)
        if digest.hexdigest() != self.sha256:
            # The model name is part of Sugo, not of the user's documents.
            raise ModelIntegrityError(
                _("model {name} failed its SHA-256 check").format(name=self.path.name)
            )


@dataclass(frozen=True)
class OcrLine:
    """One detected line of text.

    An illegible line has empty text: its area is known, its content is not.
    """

    text: str
    confidence: float
    bbox: BBox
    illegible: bool


def bundled_models() -> tuple[OcrModel, OcrModel]:
    """Return the detection and recognition models shipped in the rapidocr wheel."""
    directory = Path(rapidocr.__file__).parent / "models"
    return (
        OcrModel(directory / "PP-OCRv6_det_small.onnx", PPOCRV6_DET_SMALL_SHA256),
        OcrModel(directory / "PP-OCRv6_rec_small.onnx", PPOCRV6_REC_SMALL_SHA256),
    )


class OcrEngine:
    """A loaded OCR engine; create once and reuse, loading takes time and memory."""

    def __init__(self, detection: OcrModel, recognition: OcrModel) -> None:
        """Verify both models, then load them.

        Raises:
            ModelIntegrityError: If a model does not match its hash.
            OSError: If a model file cannot be read.
        """
        detection.verify()
        recognition.verify()
        params: dict[str, Any] = {
            "Global.use_cls": False,
            "Global.text_score": 0.0,
            "Global.log_level": "critical",
            "Det.model_path": str(detection.path),
            "Det.limit_type": "max",
            "Det.limit_side_len": OCR_DETECTION_MAX_SIDE,
            "Rec.model_path": str(recognition.path),
        }
        self._engine = RapidOCR(params=params)

    def read(self, image: PreparedImage) -> list[OcrLine]:
        """Detect and recognise the text lines of an image."""
        height, width = image.pixels.shape[:2]
        # RapidOCR follows OpenCV and expects BGR channel order.
        bgr = np.ascontiguousarray(image.pixels[..., ::-1])
        result = self._engine(bgr)
        if not isinstance(result, RapidOCROutput):
            # Only reachable if detection or recognition were switched off.
            raise TypeError("RapidOCR returned a partial result")
        if result.boxes is None or result.txts is None or result.scores is None:
            return []
        return [
            _to_line(box, text, float(score), width, height)
            for box, text, score in zip(result.boxes, result.txts, result.scores, strict=True)
        ]


def _to_line(box: Any, text: str, confidence: float, width: int, height: int) -> OcrLine:
    """Turn a detected quadrilateral and its text into a line with a normalised box."""
    points = np.asarray(box, dtype=np.float64)
    xs = np.clip(points[:, 0] / width, 0.0, 1.0)
    ys = np.clip(points[:, 1] / height, 0.0, 1.0)
    bbox = BBox(x0=float(xs.min()), y0=float(ys.min()), x1=float(xs.max()), y1=float(ys.max()))
    confidence = min(max(confidence, 0.0), 1.0)
    illegible = confidence < OCR_MIN_CONFIDENCE or not text.strip()
    return OcrLine(
        text="" if illegible else text,
        confidence=confidence,
        bbox=bbox,
        illegible=illegible,
    )
