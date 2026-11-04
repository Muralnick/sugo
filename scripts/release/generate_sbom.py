"""Generate the release CycloneDX SBOM (ADR-033).

Runs cyclonedx-py against the release virtual environment to capture the
full dependency graph (every PyPI package it ships, rapidocr included),
then adds the two files Sugo bundles directly rather than installs: the
PP-OCRv6 small OCR models and the o200k_base tokenizer vocabulary. Their
SHA-256 hashes come from ``sugo.core.constants``, the same constants the
running code checks against, so the SBOM can never drift from what is
actually verified at load time.

Usage (from the repository root, inside the release workflow):
    uv run python scripts/release/generate_sbom.py <python-in-release-venv> <output.json>

``lite`` is the only engine level in v0.1, and it never downloads a model
at install or run time (ADR-036). The day a level does, its downloader's
own manifest joins the ``_bundled_components`` list below.
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from sugo.core.constants import (  # noqa: E402
    O200K_BASE_SHA256,
    PPOCRV6_DET_SMALL_SHA256,
    PPOCRV6_REC_SMALL_SHA256,
)

_EXPECTED_ARGC = 3  # script name, python-in-release-venv, output.json


def _bundled_components() -> list[dict]:
    return [
        {
            "type": "data",
            "name": "o200k_base.tiktoken",
            "version": O200K_BASE_SHA256[:12],
            "description": (
                "Bundled tokenizer vocabulary, so token counting works "
                "offline (ADR-036, ADR-038); see "
                "src/sugo/data/tokenizers/README.md."
            ),
            "hashes": [{"alg": "SHA-256", "content": O200K_BASE_SHA256}],
            "licenses": [{"license": {"id": "MIT"}}],
        },
        {
            "type": "machine-learning-model",
            "name": "PP-OCRv6-det-small",
            "version": PPOCRV6_DET_SMALL_SHA256[:12],
            "description": (
                "Text-detection model bundled inside rapidocr 3.10.0 (ADR-004, ADR-039)."
            ),
            "hashes": [{"alg": "SHA-256", "content": PPOCRV6_DET_SMALL_SHA256}],
        },
        {
            "type": "machine-learning-model",
            "name": "PP-OCRv6-rec-small",
            "version": PPOCRV6_REC_SMALL_SHA256[:12],
            "description": (
                "Text-recognition model bundled inside rapidocr 3.10.0 (ADR-004, ADR-039)."
            ),
            "hashes": [{"alg": "SHA-256", "content": PPOCRV6_REC_SMALL_SHA256}],
        },
    ]


def main() -> None:
    if len(sys.argv) != _EXPECTED_ARGC:
        sys.stderr.write("usage: generate_sbom.py <python-in-release-venv> <output.json>\n")
        raise SystemExit(2)
    python_path, output_path = sys.argv[1], Path(sys.argv[2])

    uv = shutil.which("uv")
    if uv is None:
        sys.stderr.write("uv not found on PATH\n")
        raise SystemExit(1)

    subprocess.run(  # noqa: S603 - fixed argument list, no shell
        [
            uv,
            "run",
            "cyclonedx-py",
            "environment",
            python_path,
            "--pyproject",
            str(REPO_ROOT / "pyproject.toml"),
            "--output-reproducible",
            "--of",
            "JSON",
            "-o",
            str(output_path),
        ],
        check=True,
    )

    sbom = json.loads(output_path.read_text(encoding="utf-8"))
    sbom.setdefault("components", []).extend(_bundled_components())
    output_path.write_text(json.dumps(sbom, indent=2, sort_keys=True), encoding="utf-8")

    sys.stdout.write(f"wrote {output_path} ({len(sbom['components'])} components)\n")


if __name__ == "__main__":
    main()
