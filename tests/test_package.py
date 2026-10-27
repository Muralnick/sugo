"""Smoke tests for the package scaffold."""

import importlib

import pytest


@pytest.mark.parametrize(
    "module",
    [
        "sugo",
        "sugo.core",
        "sugo.api",
        "sugo.sources",
        "sugo.ports",
        "sugo._internal",
        "sugo._internal.net",
    ],
)
def test_module_imports(module: str) -> None:
    importlib.import_module(module)
