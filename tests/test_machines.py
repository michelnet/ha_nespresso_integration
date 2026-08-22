"""Tests for machine models and protocol helpers."""

from __future__ import annotations

import unittest

from tests.component_loader import load_component_module

enums = load_component_module("enums")
machines = load_component_module("machines")


class TemperatureTests(unittest.TestCase):
    """Protect the corrected API and its backwards-compatible alias."""

    def test_legacy_misspelling_is_an_alias(self) -> None:
        self.assertIs(enums.Temperature, enums.Temprature)
        self.assertEqual(enums.Temperature.LOW.value, 1)
        self.assertEqual(enums.Temperature.MEDIUM.value, 0)
        self.assertEqual(enums.Temperature.HIGH.value, 2)


class CoffeeMachineFactoryTests(unittest.TestCase):
    """Verify that advertised model names produce coherent machine objects."""

    def test_model_detection_is_case_insensitive(self) -> None:
        cases = {
            "expert&milk_1234": enums.MachineType.EXPERT,
            "my-vtp2-machine": enums.MachineType.VTP2,
            "NESPRESSO BLUE": enums.MachineType.BLUE,
            "Prodigio_1234": enums.MachineType.PRODIGIO,
        }

        for model_name, expected in cases.items():
            with self.subTest(model_name=model_name):
                self.assertIs(machines.get_machine_type_from_model_name(model_name), expected)

    def test_factory_preserves_identity_for_every_supported_model(self) -> None:
        cases = {
            "Expert&Milk_1234": (enums.MachineType.EXPERT, machines.ExpertMachine),
            "VTP2_1234": (enums.MachineType.VTP2, machines.VTP2Machine),
            "Blue_1234": (enums.MachineType.BLUE, machines.BlueMachine),
            "Prodigio_1234": (
                enums.MachineType.PRODIGIO,
                machines.ProdigioMachine,
            ),
        }

        for model_name, (expected_model, expected_class) in cases.items():
            with self.subTest(model_name=model_name):
                machine = machines.CoffeeMachineFactory.get_coffee_machine(model_name, "serial-1")
                self.assertIsInstance(machine, expected_class)
                self.assertIs(machine.model, expected_model)
                self.assertEqual(machine.name, model_name)
                self.assertEqual(machine.serial, "serial-1")


class MachineInformationTests(unittest.TestCase):
    """Verify version, address, and pairing information decoders."""

    def test_decode_machine_information(self) -> None:
        payload = b"".join(
            (
                (123).to_bytes(2, "big"),
                (0).to_bytes(2, "big"),
                (205).to_bytes(2, "big"),
                (10203).to_bytes(2, "big"),
                bytes.fromhex("aa bb cc dd ee ff"),
            )
        )

        self.assertEqual(
            machines.decode_machine_information(payload),
            {
                "Hardware Version": "1.23",
                "Bootloader Version": None,
                "Main Firmware Version": "2.5",
                "Connectivity Firmware Version": "1.2.3",
                "Device Address": "aa:bb:cc:dd:ee:ff",
            },
        )

        with self.assertRaises(ValueError):
            machines.decode_machine_information(payload[:13])

    def test_pairing_key_states(self) -> None:
        expected = {0: "ABSENT", 1: "TEMPORARY", 2: "PRESENT", 3: "UNDEFINED"}

        for raw_value, state in expected.items():
            with self.subTest(raw_value=raw_value):
                self.assertEqual(machines.decode_pairing_key_state(bytes([raw_value])), state)

        with self.assertRaises(ValueError):
            machines.decode_pairing_key_state(b"\x04")


if __name__ == "__main__":
    unittest.main()
