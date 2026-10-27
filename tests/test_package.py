"""Smoke tests for the package scaffold."""

import importlib

import pytest


@pytest.mark.parametrize("module", ["sugo", "sugo.core", "sugo.api", "sugo.sources", "sugo.ports"])
def test_module_imports_and_has_docstring(module: str) -> None:
    imported = importlib.import_module(module)
    assert imported.__doc__
