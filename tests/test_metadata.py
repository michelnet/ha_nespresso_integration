"""Repository metadata and Home Assistant schema-adjacent structure tests."""

from __future__ import annotations

import ast
import json
import unittest
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
COMPONENT_ROOT = ROOT / "custom_components" / "nespresso"


def _load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as json_file:
        value = json.load(json_file)
    if not isinstance(value, dict):
        raise TypeError(f"{path} must contain a JSON object")
    return value


def _yaml_scalar(value: str) -> str | int | bool | None:
    """Decode the scalar forms used by services.yaml."""
    if value == "true":
        return True
    if value == "false":
        return False
    if value in {"null", "~"}:
        return None
    if value.removeprefix("-").isdigit():
        return int(value)
    return value.strip("\"'")


def _service_yaml_paths(path: Path) -> dict[tuple[str, ...], Any]:
    """Parse the deliberately simple services.yaml into path/value pairs.

    Hassfest performs the authoritative YAML/schema validation.  This small
    stdlib-only reader lets unit tests compare the known mapping/list structure
    without installing Home Assistant or a YAML package.
    """
    values: dict[tuple[str, ...], Any] = {}
    containers: list[str] = []

    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        if "\t" in raw_line:
            raise ValueError(f"Tabs are not allowed in {path}:{line_number}")

        indentation = len(raw_line) - len(raw_line.lstrip(" "))
        if indentation % 2:
            raise ValueError(f"Unexpected indentation in {path}:{line_number}")
        level = indentation // 2
        content = raw_line.strip()

        if content.startswith("- "):
            if level == 0 or level > len(containers):
                raise ValueError(f"List without a parent in {path}:{line_number}")
            item_path = tuple(containers[:level])
            current_value = values.get(item_path)
            if current_value is None:
                current_value = []
                values[item_path] = current_value
            if not isinstance(current_value, list):
                raise ValueError(f"Mixed mapping and list in {path}:{line_number}")
            current_value.append(_yaml_scalar(content[2:].strip()))
            continue

        key, separator, raw_value = content.partition(":")
        if (
            not separator
            or not key
            or not all(character.isalnum() or character in "_-" for character in key)
        ):
            raise ValueError(f"Unsupported YAML entry in {path}:{line_number}")
        if level > len(containers):
            raise ValueError(f"Unexpected nesting in {path}:{line_number}")

        del containers[level:]
        item_path = (*containers, key)
        if item_path in values:
            raise ValueError(f"Duplicate YAML key in {path}:{line_number}")

        raw_value = raw_value.strip()
        if raw_value:
            values[item_path] = _yaml_scalar(raw_value)
        else:
            values[item_path] = None
            containers.append(key)

    return values


def _literal_constants(module_path: Path) -> dict[str, Any]:
    """Extract literal module constants without importing Home Assistant."""
    tree = ast.parse(module_path.read_text(encoding="utf-8"), filename=str(module_path))
    constants: dict[str, Any] = {}
    for node in tree.body:
        name: str | None = None
        value: ast.expr | None = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name):
                name = target.id
                value = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            name = node.target.id
            value = node.value

        if name is None or value is None:
            continue
        try:
            constants[name] = ast.literal_eval(value)
        except ValueError, TypeError:
            continue
    return constants


def _sensor_descriptions() -> list[dict[str, Any]]:
    """Extract sensor entity-description literals without importing HA."""
    sensor_path = COMPONENT_ROOT / "sensor.py"
    tree = ast.parse(sensor_path.read_text(encoding="utf-8"), filename=str(sensor_path))
    constants = _literal_constants(sensor_path)
    descriptions: list[dict[str, Any]] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Name) or node.func.id != "SensorEntityDescription":
            continue

        description: dict[str, Any] = {}
        for keyword in node.keywords:
            if keyword.arg not in {"key", "translation_key", "options"}:
                continue
            if isinstance(keyword.value, ast.Name):
                description[keyword.arg] = constants[keyword.value.id]
            else:
                description[keyword.arg] = ast.literal_eval(keyword.value)
        descriptions.append(description)

    return descriptions


class RepositoryMetadataTests(unittest.TestCase):
    """Verify the metadata HACS and Home Assistant consume."""

    def test_manifest_has_required_custom_integration_metadata(self) -> None:
        manifest = _load_json(COMPONENT_ROOT / "manifest.json")

        self.assertEqual(manifest["domain"], "nespresso")
        self.assertEqual(manifest["name"], "Nespresso")
        self.assertIs(manifest["config_flow"], True)
        self.assertEqual(manifest["integration_type"], "device")
        self.assertEqual(manifest["iot_class"], "local_polling")
        self.assertRegex(manifest["version"], r"^\d+\.\d+\.\d+$")
        self.assertTrue(manifest["codeowners"])
        self.assertTrue(all(owner.startswith("@") for owner in manifest["codeowners"]))
        self.assertTrue(manifest["documentation"].startswith("https://"))
        self.assertTrue(manifest["issue_tracker"].startswith("https://"))

        bluetooth_matchers = manifest["bluetooth"]
        self.assertTrue(bluetooth_matchers)
        constants = _literal_constants(COMPONENT_ROOT / "const.py")
        for matcher in bluetooth_matchers:
            with self.subTest(matcher=matcher):
                uuid.UUID(matcher["service_uuid"])
                self.assertIs(matcher["connectable"], True)
                self.assertEqual(matcher["service_uuid"], constants["NESPRESSO_SERVICE_UUID"])

    def test_hacs_metadata_targets_home_assistant_2026_8_or_newer(self) -> None:
        hacs = _load_json(ROOT / "hacs.json")

        self.assertEqual(hacs["name"], "Nespresso")
        self.assertIs(hacs["content_in_root"], False)
        self.assertRegex(hacs["homeassistant"], r"^\d{4}\.\d{1,2}\.\d+$")
        minimum_version = tuple(int(part) for part in hacs["homeassistant"].split("."))
        self.assertGreaterEqual(minimum_version, (2026, 8, 0))


class ServiceMetadataTests(unittest.TestCase):
    """Keep service selectors, translations, and client ranges aligned."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.services = _service_yaml_paths(COMPONENT_ROOT / "services.yaml")
        cls.english = _load_json(COMPONENT_ROOT / "translations" / "en.json")
        cls.german = _load_json(COMPONENT_ROOT / "translations" / "de.json")

    def test_service_and_field_translation_keys_match(self) -> None:
        service_names = {
            path[0] for path, value in self.services.items() if len(path) == 1 and value is None
        }
        self.assertEqual(service_names, {"coffee", "caps"})
        for locale, translation in (("en", self.english), ("de", self.german)):
            translated_services = translation["services"]
            with self.subTest(locale=locale):
                self.assertEqual(set(translated_services), service_names)
            for service_name in service_names:
                field_names = {
                    path[2]
                    for path, value in self.services.items()
                    if len(path) == 3 and path[:2] == (service_name, "fields") and value is None
                }
                with self.subTest(locale=locale, service=service_name):
                    self.assertEqual(
                        set(translated_services[service_name]["fields"]),
                        field_names,
                    )

    def test_service_number_ranges_match_the_protocol_contract(self) -> None:
        expected_ranges = {
            ("coffee", "coffee_ml"): (15, 130),
            ("coffee", "water_ml"): (25, 300),
            ("caps", "caps"): (1, 1000),
        }

        for (service_name, field_name), (minimum, maximum) in expected_ranges.items():
            with self.subTest(service=service_name, field=field_name):
                number_path = (service_name, "fields", field_name, "selector", "number")
                self.assertEqual(
                    (
                        self.services[(*number_path, "min")],
                        self.services[(*number_path, "max")],
                    ),
                    (minimum, maximum),
                )
                self.assertEqual(self.services[(*number_path, "step")], 1)

    def test_select_options_have_translation_entries(self) -> None:
        selector_fields = {
            "brew_temp": "brew_temperature",
            "brew_type": "brew_type",
        }

        for field_name, translation_key in selector_fields.items():
            select_path = ("coffee", "fields", field_name, "selector", "select")
            options = self.services[(*select_path, "options")]
            self.assertEqual(self.services[(*select_path, "translation_key")], translation_key)
            for locale, translation in (("en", self.english), ("de", self.german)):
                with self.subTest(locale=locale, field=field_name):
                    self.assertEqual(
                        set(options),
                        set(translation["selector"][translation_key]["options"]),
                    )

    def test_device_selectors_are_scoped_to_this_integration(self) -> None:
        for service_name in ("coffee", "caps"):
            with self.subTest(service=service_name):
                path = (
                    service_name,
                    "fields",
                    "device_id",
                    "selector",
                    "device",
                    "integration",
                )
                self.assertEqual(self.services[path], "nespresso")


class SensorTranslationTests(unittest.TestCase):
    """Keep coordinator keys, descriptions, and enum state translations aligned."""

    def test_sensor_keys_and_enum_options_have_translations(self) -> None:
        const_values = _literal_constants(COMPONENT_ROOT / "const.py")
        sensor_keys = tuple(const_values["SENSOR_KEYS"])
        descriptions = _sensor_descriptions()
        description_keys = tuple(description["key"] for description in descriptions)

        self.assertEqual(len(description_keys), len(set(description_keys)))
        self.assertEqual(set(description_keys), set(sensor_keys))

        for locale in ("en", "de"):
            translation = _load_json(COMPONENT_ROOT / "translations" / f"{locale}.json")
            translated_sensors = translation["entity"]["sensor"]
            with self.subTest(locale=locale):
                self.assertEqual(set(translated_sensors), set(sensor_keys))

            for description in descriptions:
                translation_key = description["translation_key"]
                translated_description = translated_sensors[translation_key]
                with self.subTest(locale=locale, sensor=translation_key):
                    self.assertTrue(translated_description["name"])
                    if options := description.get("options"):
                        self.assertEqual(set(translated_description["state"]), set(options))


if __name__ == "__main__":
    unittest.main()
