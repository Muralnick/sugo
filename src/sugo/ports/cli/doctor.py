"""Diagnostics for ``sugo doctor``: what is installed, verified and usable here.

Each check reports ``ok``, ``warning`` or ``error`` with a short detail. The
checks only read: they create no cache, download nothing and load no model
into memory beyond hashing its file.
"""

import importlib.util
import os
import platform
import shutil
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import StrEnum
from importlib.metadata import PackageNotFoundError, version

from sugo.storage.page_cache import CACHE_FILE_NAME
from sugo.storage.paths import cache_dir

# Import name -> distribution name of the packages the lite level needs (ADR-039).
LITE_PACKAGES = {
    "numpy": "numpy",
    "onnxruntime": "onnxruntime",
    "PIL": "pillow",
    "pymupdf": "pymupdf",
    "rapidocr": "rapidocr",
}
# The first PyMuPDF release whose MuPDF has the 2026 memory-safety fixes (ADR-043).
_PYMUPDF_SAFE_MAJOR = 2


class Status(StrEnum):
    """Outcome of one check."""

    OK = "ok"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True)
class Check:
    """One diagnostic line."""

    name: str
    status: Status
    detail: str


def missing_lite_packages() -> list[str]:
    """Distribution names of the lite packages that are not installed."""
    return [
        dist for module, dist in LITE_PACKAGES.items() if importlib.util.find_spec(module) is None
    ]


def run_checks() -> list[Check]:
    """Run every check, in display order."""
    checks = [
        Check("sugo", Status.OK, version("sugo")),
        Check("python", Status.OK, f"{platform.python_version()} on {platform.platform()}"),
        Check("cpus", Status.OK, str(os.cpu_count() or "unknown")),
    ]
    missing = missing_lite_packages()
    if missing:
        checks.append(
            Check(
                "level lite",
                Status.ERROR,
                f'missing {", ".join(missing)}: pip install "sugo[lite]"',
            )
        )
    else:
        checks.append(Check("level lite", Status.OK, _versions(LITE_PACKAGES.values())))
        checks.extend([_guarded("ocr models", _ocr_models), _guarded("pymupdf", _pymupdf)])
    checks.extend(
        [_guarded("tokenizer", _tokenizer), _guarded("config", _config), _cache(), _clipboard()]
    )
    return checks


def _versions(dists: Iterable[str]) -> str:
    return ", ".join(f"{name} {_version(name)}" for name in dists)


def _version(dist: str) -> str:
    try:
        return version(dist)
    except PackageNotFoundError:
        return "not installed"


def _guarded(name: str, check: Callable[[], Check]) -> Check:
    """Run a check; an unexpected failure is reported, not raised, so the others still run."""
    try:
        return check()
    except Exception as error:  # noqa: BLE001 - reported to the user as a failed check
        return Check(name, Status.ERROR, f"{type(error).__name__}: {error}")


def _ocr_models() -> Check:
    from sugo.extractors.image.ocr_engine import bundled_models

    models = bundled_models()
    for model in models:
        model.verify()
    return Check("ocr models", Status.OK, f"{len(models)} models, SHA-256 verified")


def _pymupdf() -> Check:
    installed = version("pymupdf")
    if int(installed.split(".", 1)[0]) < _PYMUPDF_SAFE_MAJOR:
        return Check(
            "pymupdf",
            Status.WARNING,
            f"{installed} has known memory-safety bugs; convert only PDFs you trust",
        )
    return Check("pymupdf", Status.OK, installed)


def _tokenizer() -> Check:
    from sugo.metrics.tokenizer import get_encoding

    get_encoding()
    return Check("tokenizer", Status.OK, "o200k_base, SHA-256 verified")


def _config() -> Check:
    from sugo.config.settings import ConfigError, load, printable, user_config_path

    try:
        loaded = load()
    except ConfigError as error:
        return Check("config", Status.ERROR, str(error))
    files = ", ".join(printable(str(path)) for path in loaded.sources) or (
        f"defaults (none at {printable(str(user_config_path()))})"
    )
    # The MCP server reads the user file only (ADR-051): show what it applies too.
    mcp = load(project=False, environment=False).settings
    detail = (
        f"{files}; languages {', '.join(loaded.settings.languages)}"
        f"; sugo mcp: languages {', '.join(mcp.languages)}"
    )
    if loaded.warnings:
        return Check("config", Status.WARNING, f"{detail}; " + "; ".join(loaded.warnings))
    return Check("config", Status.OK, detail)


def _cache() -> Check:
    directory = cache_dir()
    database = directory / CACHE_FILE_NAME
    if not database.exists():
        return Check("cache", Status.OK, f"{directory} (empty)")
    size_mb = database.stat().st_size / 1_000_000
    return Check("cache", Status.OK, f"{directory} ({size_mb:.1f} MB)")


def _clipboard() -> Check:
    if sys.platform in ("win32", "darwin"):
        return Check("clipboard", Status.OK, "native")
    tools = [tool for tool in ("wl-paste", "xclip") if shutil.which(tool)]
    if tools:
        return Check("clipboard", Status.OK, ", ".join(tools))
    return Check("clipboard", Status.WARNING, "install wl-clipboard (Wayland) or xclip (X11)")
