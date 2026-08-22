"""Unit tests for config-flow authentication-token handling."""

from __future__ import annotations

import unittest

try:
    from .component_loader import load_component_module
except ImportError:
    from component_loader import load_component_module

auth = load_component_module("auth")


class AuthenticationTokenTests(unittest.TestCase):
    """Verify optional-token normalization and format checks."""

    def test_normalize_optional_token(self) -> None:
        self.assertIsNone(auth.normalize_auth_token(None))
        self.assertIsNone(auth.normalize_auth_token(""))
        self.assertIsNone(auth.normalize_auth_token("   "))
        self.assertEqual(
            auth.normalize_auth_token(" 001122aAbBcCdDeE "),
            "001122aAbBcCdDeE",
        )

    def test_accepts_exactly_eight_hexadecimal_bytes(self) -> None:
        for token in ("0011223344556677", "aabbccddeeffAABB", "FFFFFFFFFFFFFFFF"):
            with self.subTest(token=token):
                self.assertTrue(auth.is_valid_auth_token(token))

    def test_rejects_missing_malformed_or_wrong_length_token(self) -> None:
        for token in (
            None,
            "",
            "001122334455667",
            "00112233445566778",
            "00112233445566gg",
            "0011-2233-445566",
        ):
            with self.subTest(token=token):
                self.assertFalse(auth.is_valid_auth_token(token))


if __name__ == "__main__":
    unittest.main()
