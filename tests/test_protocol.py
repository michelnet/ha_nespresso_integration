"""Tests for command responses and other pure protocol modules."""

from __future__ import annotations

import unittest

from tests.component_loader import load_component_module

command_response = load_component_module("commandResponse")
error_information = load_component_module("errorInformation")
machine_state = load_component_module("machineState")


class CommandResponseTests(unittest.TestCase):
    """Verify response-code and condition decoding."""

    @staticmethod
    def _response(response_code: int, condition: int = 0) -> bytearray:
        payload = bytearray(20)
        payload[3] = response_code
        payload[4] = condition
        return payload

    def test_top_level_response_codes(self) -> None:
        cases = {
            32: command_response.CommandResponse.DONE,
            54: command_response.CommandResponse.OUT_OF_RANGE,
            255: command_response.CommandResponse.UNDEFINED,
        }

        for response_code, expected in cases.items():
            with self.subTest(response_code=response_code):
                self.assertIs(
                    command_response.from_byte_buffer(self._response(response_code)),
                    expected,
                )

    def test_conditions_not_fulfilled(self) -> None:
        cases = {
            1: command_response.CommandResponse.INVALID_STATE,
            2: command_response.CommandResponse.INVALID_STATE,
            3: command_response.CommandResponse.CAPSULE_CONTAINER_FULL,
            4: command_response.CommandResponse.OBSTACLE_DETECTED,
            5: command_response.CommandResponse.DESCALE_ON,
            6: command_response.CommandResponse.LAST_ACTION_NOT_FINISHED,
            7: command_response.CommandResponse.NOT_ABORTABLE_ACTION,
            8: command_response.CommandResponse.SLIDER_OPEN,
            9: command_response.CommandResponse.NO_PROGRAMMED_BREW_ACTIVE,
            16: command_response.CommandResponse.PUMP_RUNNING,
            17: command_response.CommandResponse.MOTOR_RUNNING,
            18: command_response.CommandResponse.SLIDER_NOT_BEEN_OPENED,
            99: command_response.CommandResponse.UNDEFINED,
        }

        for condition, expected in cases.items():
            with self.subTest(condition=condition):
                self.assertIs(
                    command_response.from_byte_buffer(self._response(36, condition)),
                    expected,
                )

    def test_truncated_response_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            command_response.from_byte_buffer(b"\x00\x00\x00")
        with self.assertRaises(ValueError):
            command_response.from_byte_buffer(b"\x00\x00\x00\x24")


class MachineStateTests(unittest.TestCase):
    """Verify bit helpers and safe state conversion."""

    def test_select_bits(self) -> None:
        payload = bytes.fromhex("a5 3c")

        self.assertEqual(machine_state.select_bits(payload, 0, 4), 0xA)
        self.assertEqual(machine_state.select_bits(payload, 4, 8), 0x53)
        self.assertEqual(machine_state.select_bits(payload, 12, 4), 0xC)

    def test_default_machine_state_handles_unknown_values(self) -> None:
        self.assertEqual(machine_state.default_machine_state_from(2), "READY")
        self.assertEqual(machine_state.default_machine_state_from(255), "UNKNOWN")


class ErrorInformationTests(unittest.TestCase):
    """Verify packed error data decoding."""

    def test_decode_error_information(self) -> None:
        decoded = error_information.to_error_information(bytes.fromhex("01 30 26 03"))

        self.assertEqual(decoded.error_number, 1)
        self.assertIs(
            decoded.error_category,
            error_information.ErrorCategory.DEVICE_ERROR_MAIN_SYSTEM,
        )
        self.assertEqual(decoded.error_sub_code, 0x2603)

        with self.assertRaises(ValueError):
            error_information.to_error_information(b"\x01\x30\x26")


if __name__ == "__main__":
    unittest.main()
