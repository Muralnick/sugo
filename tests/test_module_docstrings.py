"""Every Python module, private ones included, starts with a docstring (CODE_STYLE.md).

ruff's D100 skips private modules (`_name.py`), so this test closes that gap.
Files are parsed with `ast`, never imported or executed.
"""

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CHECKED_DIRS = ("src", "tests", "packs")


def _python_files() -> list[Path]:
    return sorted(
        path
        for directory in CHECKED_DIRS
        if (REPO_ROOT / directory).is_dir()
        for path in (REPO_ROOT / directory).rglob("*.py")
    )


def test_python_files_are_found() -> None:
    # Guards against a moved directory turning the check below into a no-op.
    assert any(path.name == "__init__.py" for path in _python_files())


@pytest.mark.parametrize(
    "path", _python_files(), ids=lambda path: path.relative_to(REPO_ROOT).as_posix()
)
def test_module_starts_with_docstring(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    docstring = ast.get_docstring(tree)
    assert docstring, "module must start with a non-empty docstring"
