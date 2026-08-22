"""Authentication-token helpers for the Nespresso integration."""

from __future__ import annotations

import string

AUTH_TOKEN_LENGTH = 16


def normalize_auth_token(value: str | None) -> str | None:
    """Strip a token and treat an empty optional field as no token."""

    if value is None:
        return None

    normalized = value.strip()
    return normalized or None


def is_valid_auth_token(value: str | None) -> bool:
    """Return whether a token is an eight-byte hexadecimal value."""

    return bool(
        value
        and len(value) == AUTH_TOKEN_LENGTH
        and all(character in string.hexdigits for character in value)
    )
