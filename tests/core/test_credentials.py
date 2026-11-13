"""Tests for the shared private-key check (ADR-053), used by MCP, the API and the loaders."""

import pytest

from sugo.core.credentials import holds_private_key


@pytest.mark.parametrize(
    ("text", "found"),
    [
        ("-----BEGIN RSA PRIVATE KEY-----", True),
        ("-----BEGIN PGP PRIVATE KEY BLOCK-----", True),
        ("\\-----END ENCRYPTED PRIVATE KEY-----", True),
        ("BEGIN Private Key ———", True),
        ("BEGIN PRIVATE\nKEY\n\\-----", True),
        # Table cells join wrapped lines with <br>.
        ("| BEGIN PRIVATE<br>KEY----- |", True),
        ("-----BEGIN PUBLIC KEY-----", False),
        ("Keep the private key -- never share it.", False),
        ("The private key is stored in a vault.", False),
    ],
)
def test_private_key_headers_are_recognised(text: str, found: bool) -> None:
    assert holds_private_key(text) is found


def test_any_of_several_texts_is_enough() -> None:
    assert holds_private_key("plain text", "-----BEGIN RSA PRIVATE KEY-----")
    assert not holds_private_key()
