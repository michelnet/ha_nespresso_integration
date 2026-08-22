"""Structural tests for every bundled translation."""

from __future__ import annotations

import json
import string
import unittest
from collections import Counter
from pathlib import Path
from typing import Any

TRANSLATION_ROOT = (
    Path(__file__).resolve().parents[1] / "custom_components" / "nespresso" / "translations"
)
LOCALES = ("en", "de", "pt", "sv")


def _load_translation(locale: str) -> dict[str, Any]:
    path = TRANSLATION_ROOT / f"{locale}.json"
    with path.open(encoding="utf-8") as translation_file:
        value = json.load(translation_file)
    if not isinstance(value, dict):
        raise TypeError(f"{path} must contain a JSON object")
    return value


def _placeholders(value: str) -> Counter[str]:
    return Counter(
        field_name
        for _, field_name, _, _ in string.Formatter().parse(value)
        if field_name is not None
    )


class TranslationStructureTests(unittest.TestCase):
    """Keep user-facing locale files structurally compatible."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.translations = {locale: _load_translation(locale) for locale in LOCALES}

    def test_locale_files_are_valid_json_objects(self) -> None:
        for locale, translation in self.translations.items():
            with self.subTest(locale=locale):
                self.assertIsInstance(translation, dict)
                self.assertTrue(translation)

    def test_locales_have_matching_keys_and_placeholders(self) -> None:
        for locale in LOCALES[1:]:
            with self.subTest(locale=locale):
                self._assert_matching_structure(
                    self.translations["en"], self.translations[locale], path=()
                )

    def test_translations_do_not_use_indirect_key_references(self) -> None:
        for locale, translation in self.translations.items():
            with self.subTest(locale=locale):
                self._assert_no_key_references(translation, path=())

    def _assert_matching_structure(self, english: Any, german: Any, path: tuple[str, ...]) -> None:
        location = ".".join(path) or "<root>"
        self.assertIs(
            type(german),
            type(english),
            f"JSON type mismatch at {location}",
        )

        if isinstance(english, dict):
            self.assertEqual(set(english), set(german), f"Translation key mismatch at {location}")
            for key in english:
                self._assert_matching_structure(english[key], german[key], path=(*path, key))
            return

        if isinstance(english, list):
            self.assertEqual(len(english), len(german), f"List length mismatch at {location}")
            for index, english_item in enumerate(english):
                self._assert_matching_structure(
                    english_item, german[index], path=(*path, str(index))
                )
            return

        if isinstance(english, str):
            self.assertEqual(
                _placeholders(english),
                _placeholders(german),
                f"Placeholder mismatch at {location}",
            )

    def _assert_no_key_references(self, value: Any, path: tuple[str, ...]) -> None:
        if isinstance(value, dict):
            for key, nested_value in value.items():
                self._assert_no_key_references(nested_value, (*path, key))
            return

        if isinstance(value, list):
            for index, nested_value in enumerate(value):
                self._assert_no_key_references(nested_value, (*path, str(index)))
            return

        if isinstance(value, str):
            self.assertNotIn(
                "[%key:",
                value,
                f"Indirect key reference at {'.'.join(path)}",
            )


if __name__ == "__main__":
    unittest.main()
