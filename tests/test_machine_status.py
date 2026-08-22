"""Tests for status and characteristic decoders."""

from __future__ import annotations

import unittest

from tests.component_loader import load_component_module

machine_status = load_component_module("machineStatus")


class MachineStatusTests(unittest.TestCase):
    """Verify decoding of the packed machine status characteristic."""

    def test_decode_known_status_payload(self) -> None:
        raw_data = bytes.fromhex("55 a2 00 00 00 00 01 02 03")

        decoded = machine_status.MachineStatus(raw_data).decode()

        self.assertEqual(
            decoded,
            {
                "water_is_empty": "EMPTY",
                "descaling_needed": "NEEDED",
                "capsule_mechanism_jammed": "JAMMED",
                "water_fresh": "NOT_FRESH",
                "state": "READY",
                "descaling_counter": 0x010203,
            },
        )

    def test_select_bits_uses_network_bit_order(self) -> None:
        status = machine_status.MachineStatus(bytes.fromhex("a5 3c"))

        self.assertEqual(status.select_bits(0, 4), 0xA)
        self.assertEqual(status.select_bits(4, 8), 0x53)
        self.assertEqual(status.select_bits(12, 4), 0xC)

    def test_invalid_buffer_and_bit_ranges_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            machine_status.MachineStatus(b"\x00" * 8).decode()

        status = machine_status.MachineStatus(b"\x00\x00")
        for start_bit, length in ((-1, 1), (0, 0), (15, 2)):
            with self.subTest(start_bit=start_bit, length=length):
                with self.assertRaises(ValueError):
                    status.select_bits(start_bit, length)


class BaseDecodeTests(unittest.TestCase):
    """Verify all scalar characteristic decoder formats."""

    def test_capsule_counter_is_big_endian(self) -> None:
        decoder = machine_status.BaseDecode("caps_number", "caps_number")

        self.assertEqual(decoder.decode_data(bytes.fromhex("03 e8")), {"caps_number": 1000})

    def test_pairing_status(self) -> None:
        decoder = machine_status.BaseDecode("paired", "pairing_status")

        for raw_value, expected in ((0, False), (1, False), (2, True)):
            with self.subTest(raw_value=raw_value):
                self.assertEqual(decoder.decode_data(bytes([raw_value])), {"paired": expected})

        for raw_value in (3, 255):
            with self.subTest(raw_value=raw_value), self.assertRaises(ValueError):
                decoder.decode_data(bytes([raw_value]))

    def test_slider_and_water_hardness(self) -> None:
        slider = machine_status.BaseDecode("slider", "slider")
        hardness = machine_status.BaseDecode("water_hardness", "water_hardness")

        self.assertEqual(slider.decode_data(b"\x00"), {"slider": "OPEN"})
        self.assertEqual(slider.decode_data(b"\x02"), {"slider": "CLOSED"})
        self.assertEqual(
            hardness.decode_data(bytes.fromhex("ff ff 04")),
            {"water_hardness": "LEVEL_4"},
        )

    def test_unknown_format_is_returned_unchanged(self) -> None:
        decoder = machine_status.BaseDecode("raw", "unknown")
        raw_data = b"\x01\x02"

        self.assertEqual(decoder.decode_data(raw_data), {"raw": raw_data})

    def test_empty_scalar_characteristics_are_rejected(self) -> None:
        for format_type in ("caps_number", "pairing_status", "slider"):
            with self.subTest(format_type=format_type):
                decoder = machine_status.BaseDecode("value", format_type)
                with self.assertRaises(ValueError):
                    decoder.decode_data(b"")


if __name__ == "__main__":
    unittest.main()
