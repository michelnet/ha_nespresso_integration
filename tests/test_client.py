"""Async unit tests for the Home Assistant independent Bluetooth client."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, call, patch

from tests.component_loader import load_component_module

enums = load_component_module("enums")
machines = load_component_module("machines")
nespresso = load_component_module("nespresso")

VALID_STATE = bytes.fromhex("00 02 00 00 00 00 00 00 01")


class ClientLifecycleTests(unittest.IsolatedAsyncioTestCase):
    """Verify connection cleanup and error behavior."""

    async def test_disconnect_is_idempotent(self) -> None:
        client = nespresso.NespressoClient(mac="AA:BB:CC:DD:EE:FF")

        await client.disconnect()

        connection = SimpleNamespace(disconnect=AsyncMock())
        client._conn = connection
        await client.disconnect()

        connection.disconnect.assert_awaited_once_with()
        self.assertIsNone(client._conn)

    async def test_write_errors_propagate_to_the_caller(self) -> None:
        client = nespresso.NespressoClient(mac="AA:BB:CC:DD:EE:FF")
        client.machine = SimpleNamespace(name="Test machine")
        client._conn = SimpleNamespace(
            write_gatt_char=AsyncMock(side_effect=OSError("Bluetooth unavailable"))
        )

        with self.assertRaisesRegex(OSError, "Bluetooth unavailable"):
            await client._send_command("characteristic", b"command")

    async def test_onboarding_status_uses_the_pairing_key_state_protocol(self) -> None:
        client = nespresso.NespressoClient(mac="AA:BB:CC:DD:EE:FF")

        for raw_value, expected in ((0, False), (1, False), (2, True)):
            with self.subTest(raw_value=raw_value):
                connection = SimpleNamespace(
                    read_gatt_char=AsyncMock(return_value=bytes([raw_value]))
                )
                self.assertIs(await client.get_onboard_status(connection), expected)

        for payload in (b"", b"\x03", b"\xff"):
            with self.subTest(payload=payload):
                connection = SimpleNamespace(read_gatt_char=AsyncMock(return_value=payload))
                with self.assertRaises(nespresso.NespressoConnectionError):
                    await client.get_onboard_status(connection)

    async def test_stored_key_authenticates_without_os_pairing(self) -> None:
        address = "AA:BB:CC:DD:EE:FF"
        device = SimpleNamespace(address=address, name="Expert_1234")
        first_connection = SimpleNamespace(
            address=address,
            is_connected=True,
            pair=AsyncMock(return_value=True),
            read_gatt_char=AsyncMock(return_value=VALID_STATE),
            write_gatt_char=AsyncMock(),
            disconnect=AsyncMock(),
        )
        second_connection = SimpleNamespace(
            address=address,
            is_connected=True,
            pair=AsyncMock(return_value=True),
            read_gatt_char=AsyncMock(return_value=VALID_STATE),
            write_gatt_char=AsyncMock(),
            disconnect=AsyncMock(),
        )
        auth_code = "0123456789abcdef"
        auth_bytes = bytes.fromhex(auth_code)
        client = nespresso.NespressoClient(auth_code=auth_code, mac=address)

        establish = AsyncMock(side_effect=(first_connection, second_connection))
        with patch.object(nespresso, "establish_connection", establish):
            await client.connect(device)
            await client.disconnect()
            await client.connect(device)

        first_connection.pair.assert_not_awaited()
        second_connection.pair.assert_not_awaited()
        first_connection.write_gatt_char.assert_awaited_once_with(
            nespresso.CHAR_UUID_AUTH, auth_bytes, response=True
        )
        first_connection.read_gatt_char.assert_awaited_once_with(nespresso.CHAR_UUID_STATE)
        second_connection.write_gatt_char.assert_awaited_once_with(
            nespresso.CHAR_UUID_AUTH, auth_bytes, response=True
        )
        second_connection.read_gatt_char.assert_awaited_once_with(nespresso.CHAR_UUID_STATE)

    async def test_onboarded_machine_without_token_is_not_modified(self) -> None:
        address = "AA:BB:CC:DD:EE:FF"
        device = SimpleNamespace(address=address, name="Expert_1234")
        connection = SimpleNamespace(
            address=address,
            is_connected=True,
            pair=AsyncMock(),
            read_gatt_char=AsyncMock(return_value=b"\x02"),
            write_gatt_char=AsyncMock(),
            disconnect=AsyncMock(),
        )
        client = nespresso.NespressoClient(mac=address)
        generate_auth_key = Mock(side_effect=AssertionError("must not generate another token"))

        with (
            patch.object(nespresso, "establish_connection", AsyncMock(return_value=connection)),
            patch.object(client, "generate_auth_key", generate_auth_key),
            self.assertRaises(nespresso.NespressoAuthenticationError),
        ):
            await client.connect(device)

        generate_auth_key.assert_not_called()
        connection.write_gatt_char.assert_not_awaited()
        connection.pair.assert_not_awaited()
        connection.disconnect.assert_awaited_once_with()

    async def test_new_onboarding_installs_and_reuses_one_generated_key(self) -> None:
        address = "AA:BB:CC:DD:EE:FF"
        device = SimpleNamespace(address=address, name="Expert_1234")
        connection = SimpleNamespace(
            address=address,
            is_connected=True,
            pair=AsyncMock(return_value=True),
            read_gatt_char=AsyncMock(side_effect=(b"\x00", b"\x00", b"\x02", VALID_STATE)),
            write_gatt_char=AsyncMock(),
            disconnect=AsyncMock(),
        )
        client = nespresso.NespressoClient(mac=address)
        generated_key = "0123456789abcdef"

        with (
            patch.object(nespresso, "establish_connection", AsyncMock(return_value=connection)),
            patch.object(nespresso.asyncio, "sleep", AsyncMock()) as sleep,
            patch.object(
                nespresso.NespressoClient,
                "generate_auth_key",
                return_value=generated_key,
            ),
        ):
            await client.connect(device)

        auth_bytes = bytes.fromhex(generated_key)
        self.assertEqual(client.auth_code, generated_key)
        connection.pair.assert_not_awaited()
        self.assertEqual(
            sleep.await_args_list,
            [
                call(nespresso.PAIRING_STATE_POLL_SECONDS),
                call(nespresso.ONBOARDING_SETTLE_SECONDS),
            ],
        )
        self.assertEqual(
            connection.write_gatt_char.await_args_list,
            [
                call(nespresso.CHAR_UUID_PAIR, bytearray([1]), response=True),
                call(nespresso.CHAR_UUID_AUTH, auth_bytes, response=True),
                call(nespresso.CHAR_UUID_AUTH, auth_bytes, response=True),
            ],
        )

    async def test_supplied_backup_token_is_never_replaced_during_onboarding(self) -> None:
        address = "AA:BB:CC:DD:EE:FF"
        device = SimpleNamespace(address=address, name="Expert_1234")
        auth_code = "0123456789abcdef"
        auth_bytes = bytes.fromhex(auth_code)
        rejected = nespresso.BleakGATTProtocolError(
            nespresso.BleakGATTProtocolErrorCode.UNLIKELY_ERROR
        )
        rejected_again = nespresso.BleakGATTProtocolError(
            nespresso.BleakGATTProtocolErrorCode.UNLIKELY_ERROR
        )
        connection = SimpleNamespace(
            address=address,
            is_connected=True,
            pair=AsyncMock(),
            read_gatt_char=AsyncMock(
                side_effect=(
                    b"\x00",
                    b"\x00",
                    b"\x00",
                    b"\x00",
                    b"\x02",
                    VALID_STATE,
                )
            ),
            write_gatt_char=AsyncMock(side_effect=(rejected, rejected_again, None, None, None)),
            disconnect=AsyncMock(),
        )
        client = nespresso.NespressoClient(auth_code=auth_code, mac=address)
        generate_auth_key = Mock(side_effect=AssertionError("must not replace supplied token"))

        with (
            patch.object(nespresso, "establish_connection", AsyncMock(return_value=connection)),
            patch.object(nespresso.asyncio, "sleep", AsyncMock()) as sleep,
            patch.object(client, "generate_auth_key", generate_auth_key),
        ):
            await client.connect(device)

        self.assertEqual(client.auth_code, auth_code)
        generate_auth_key.assert_not_called()
        connection.pair.assert_not_awaited()
        self.assertEqual(
            sleep.await_args_list,
            [
                call(nespresso.PAIRING_STATE_POLL_SECONDS),
                call(nespresso.PAIRING_STATE_POLL_SECONDS),
                call(nespresso.PAIRING_STATE_POLL_SECONDS),
                call(nespresso.ONBOARDING_SETTLE_SECONDS),
            ],
        )
        self.assertEqual(
            connection.write_gatt_char.await_args_list,
            [
                call(nespresso.CHAR_UUID_AUTH, auth_bytes, response=True),
                call(nespresso.CHAR_UUID_AUTH, auth_bytes, response=True),
                call(nespresso.CHAR_UUID_PAIR, bytearray([1]), response=True),
                call(nespresso.CHAR_UUID_AUTH, auth_bytes, response=True),
                call(nespresso.CHAR_UUID_AUTH, auth_bytes, response=True),
            ],
        )

    async def test_temporary_onboarding_state_is_polled_until_final(self) -> None:
        address = "AA:BB:CC:DD:EE:FF"
        device = SimpleNamespace(address=address, name="Expert_1234")
        auth_code = "0123456789abcdef"
        connection = SimpleNamespace(
            address=address,
            is_connected=True,
            pair=AsyncMock(),
            read_gatt_char=AsyncMock(
                side_effect=(
                    b"\x00",
                    b"\x00",
                    b"\x01",
                    b"\x01",
                    b"\x02",
                    VALID_STATE,
                )
            ),
            write_gatt_char=AsyncMock(),
            disconnect=AsyncMock(),
        )
        client = nespresso.NespressoClient(mac=address)

        with (
            patch.object(nespresso, "establish_connection", AsyncMock(return_value=connection)),
            patch.object(nespresso.asyncio, "sleep", AsyncMock()) as sleep,
            patch.object(client, "generate_auth_key", return_value=auth_code),
        ):
            await client.connect(device)

        self.assertEqual(
            sleep.await_args_list,
            [
                call(nespresso.PAIRING_STATE_POLL_SECONDS),
                call(nespresso.ONBOARDING_SETTLE_SECONDS),
                call(nespresso.PAIRING_STATE_POLL_SECONDS),
                call(nespresso.PAIRING_STATE_POLL_SECONDS),
            ],
        )
        self.assertEqual(client.auth_code, auth_code)
        self.assertTrue(client.is_onboard)

    async def test_second_backup_token_attempt_can_succeed_without_onboarding(self) -> None:
        address = "AA:BB:CC:DD:EE:FF"
        device = SimpleNamespace(address=address, name="Expert_1234")
        auth_code = "0123456789abcdef"
        rejected = nespresso.BleakGATTProtocolError(
            nespresso.BleakGATTProtocolErrorCode.UNLIKELY_ERROR
        )
        connection = SimpleNamespace(
            address=address,
            is_connected=True,
            pair=AsyncMock(),
            read_gatt_char=AsyncMock(side_effect=(b"\x00", b"\x00", VALID_STATE)),
            write_gatt_char=AsyncMock(side_effect=(rejected, None)),
            disconnect=AsyncMock(),
        )
        client = nespresso.NespressoClient(auth_code=auth_code, mac=address)

        with (
            patch.object(nespresso, "establish_connection", AsyncMock(return_value=connection)),
            patch.object(nespresso.asyncio, "sleep", AsyncMock()),
        ):
            await client.connect(device)

        self.assertEqual(connection.write_gatt_char.await_count, 2)
        self.assertNotIn(
            nespresso.CHAR_UUID_PAIR,
            [awaited.args[0] for awaited in connection.write_gatt_char.await_args_list],
        )
        self.assertEqual(client.auth_code, auth_code)
        connection.pair.assert_not_awaited()

    async def test_temporary_onboarding_state_times_out_without_writing(self) -> None:
        address = "AA:BB:CC:DD:EE:FF"
        device = SimpleNamespace(address=address, name="Expert_1234")
        connection = SimpleNamespace(
            address=address,
            is_connected=True,
            pair=AsyncMock(),
            read_gatt_char=AsyncMock(return_value=b"\x01"),
            write_gatt_char=AsyncMock(),
            disconnect=AsyncMock(),
        )
        client = nespresso.NespressoClient(mac=address)

        with (
            patch.object(nespresso, "establish_connection", AsyncMock(return_value=connection)),
            patch.object(nespresso.asyncio, "sleep", AsyncMock()),
            patch.object(nespresso, "PAIRING_STATE_MAX_ATTEMPTS", 2),
            self.assertRaises(nespresso.NespressoConnectionError),
        ):
            await client.connect(device)

        connection.write_gatt_char.assert_not_awaited()
        connection.disconnect.assert_awaited_once_with()

    async def test_transient_auth_failures_are_connection_errors(self) -> None:
        address = "AA:BB:CC:DD:EE:FF"
        device = SimpleNamespace(address=address, name="Expert_1234")
        auth_code = "0123456789abcdef"

        for write_side_effect, read_side_effect in (
            (TimeoutError("write timed out"), None),
            (None, TimeoutError("read timed out")),
        ):
            with self.subTest(
                write_failed=write_side_effect is not None,
                read_failed=read_side_effect is not None,
            ):
                connection = SimpleNamespace(
                    address=address,
                    is_connected=True,
                    pair=AsyncMock(),
                    read_gatt_char=AsyncMock(side_effect=read_side_effect),
                    write_gatt_char=AsyncMock(side_effect=write_side_effect),
                    disconnect=AsyncMock(),
                )
                client = nespresso.NespressoClient(auth_code=auth_code, mac=address)

                with (
                    patch.object(
                        nespresso, "establish_connection", AsyncMock(return_value=connection)
                    ),
                    self.assertRaises(nespresso.NespressoConnectionError) as raised,
                ):
                    await client.connect(device)

                self.assertIsInstance(raised.exception.__cause__, TimeoutError)
                connection.disconnect.assert_awaited_once_with()

    async def test_link_security_errors_pair_once_then_retry_the_token(self) -> None:
        address = "AA:BB:CC:DD:EE:FF"
        device = SimpleNamespace(address=address, name="Expert_1234")
        auth_code = "0123456789abcdef"
        auth_bytes = bytes.fromhex(auth_code)
        security_errors = {
            "att": nespresso.BleakGATTProtocolError(
                nespresso.BleakGATTProtocolErrorCode.INSUFFICIENT_AUTHENTICATION
            ),
            "bluez": nespresso.BleakDBusError("org.bluez.Error.NotPermitted", ["Not paired"]),
        }

        for error_source, security_error in security_errors.items():
            with self.subTest(error_source=error_source):
                connection = SimpleNamespace(
                    address=address,
                    is_connected=True,
                    pair=AsyncMock(),
                    read_gatt_char=AsyncMock(return_value=VALID_STATE),
                    write_gatt_char=AsyncMock(side_effect=(security_error, None)),
                    disconnect=AsyncMock(),
                )
                client = nespresso.NespressoClient(auth_code=auth_code, mac=address)

                with (
                    patch.object(
                        nespresso, "establish_connection", AsyncMock(return_value=connection)
                    ),
                    patch.object(nespresso.asyncio, "sleep", AsyncMock()) as sleep,
                ):
                    await client.connect(device)

                connection.pair.assert_awaited_once_with()
                sleep.assert_awaited_once_with(nespresso.PAIRING_SETTLE_SECONDS)
                self.assertEqual(
                    connection.write_gatt_char.await_args_list,
                    [
                        call(nespresso.CHAR_UUID_AUTH, auth_bytes, response=True),
                        call(nespresso.CHAR_UUID_AUTH, auth_bytes, response=True),
                    ],
                )

    async def test_repeated_link_security_error_is_a_connection_error(self) -> None:
        address = "AA:BB:CC:DD:EE:FF"
        device = SimpleNamespace(address=address, name="Expert_1234")
        security_errors = tuple(
            nespresso.BleakGATTProtocolError(
                nespresso.BleakGATTProtocolErrorCode.INSUFFICIENT_AUTHENTICATION
            )
            for _ in range(2)
        )
        connection = SimpleNamespace(
            address=address,
            is_connected=True,
            pair=AsyncMock(),
            read_gatt_char=AsyncMock(),
            write_gatt_char=AsyncMock(side_effect=security_errors),
            disconnect=AsyncMock(),
        )
        client = nespresso.NespressoClient(auth_code="0123456789abcdef", mac=address)

        with (
            patch.object(nespresso, "establish_connection", AsyncMock(return_value=connection)),
            patch.object(nespresso.asyncio, "sleep", AsyncMock()),
            self.assertRaises(nespresso.NespressoConnectionError),
        ):
            await client.connect(device)

        connection.pair.assert_awaited_once_with()
        connection.disconnect.assert_awaited_once_with()

    async def test_explicit_final_state_rejection_is_an_auth_error(self) -> None:
        address = "AA:BB:CC:DD:EE:FF"
        device = SimpleNamespace(address=address, name="Expert_1234")
        rejected = nespresso.BleakGATTProtocolError(
            nespresso.BleakGATTProtocolErrorCode.UNLIKELY_ERROR
        )
        connection = SimpleNamespace(
            address=address,
            is_connected=True,
            pair=AsyncMock(),
            read_gatt_char=AsyncMock(return_value=b"\x02"),
            write_gatt_char=AsyncMock(side_effect=(rejected, rejected)),
            disconnect=AsyncMock(),
        )
        client = nespresso.NespressoClient(auth_code="0123456789abcdef", mac=address)

        with (
            patch.object(nespresso, "establish_connection", AsyncMock(return_value=connection)),
            patch.object(nespresso.asyncio, "sleep", AsyncMock()) as sleep,
            self.assertRaises(nespresso.NespressoAuthenticationError),
        ):
            await client.connect(device)

        connection.pair.assert_not_awaited()
        sleep.assert_awaited_once_with(nespresso.PAIRING_STATE_POLL_SECONDS)
        connection.disconnect.assert_awaited_once_with()

    async def test_protected_read_rejection_is_an_auth_error(self) -> None:
        address = "AA:BB:CC:DD:EE:FF"
        device = SimpleNamespace(address=address, name="Expert_1234")
        read_rejections = tuple(
            nespresso.BleakGATTProtocolError(
                nespresso.BleakGATTProtocolErrorCode.READ_NOT_PERMITTED
            )
            for _ in range(2)
        )
        connection = SimpleNamespace(
            address=address,
            is_connected=True,
            pair=AsyncMock(),
            read_gatt_char=AsyncMock(side_effect=(read_rejections[0], b"\x02", read_rejections[1])),
            write_gatt_char=AsyncMock(),
            disconnect=AsyncMock(),
        )
        client = nespresso.NespressoClient(auth_code="0123456789abcdef", mac=address)

        with (
            patch.object(nespresso, "establish_connection", AsyncMock(return_value=connection)),
            patch.object(nespresso.asyncio, "sleep", AsyncMock()),
            self.assertRaises(nespresso.NespressoAuthenticationError),
        ):
            await client.connect(device)

        self.assertEqual(connection.write_gatt_char.await_count, 2)
        connection.pair.assert_not_awaited()
        connection.disconnect.assert_awaited_once_with()

    async def test_late_final_state_prevents_onboarding_write(self) -> None:
        address = "AA:BB:CC:DD:EE:FF"
        device = SimpleNamespace(address=address, name="Expert_1234")
        rejections = tuple(
            nespresso.BleakGATTProtocolError(nespresso.BleakGATTProtocolErrorCode.UNLIKELY_ERROR)
            for _ in range(2)
        )
        connection = SimpleNamespace(
            address=address,
            is_connected=True,
            pair=AsyncMock(),
            # NONE is confirmed before the second auth attempt, but the
            # immediate pre-onboarding check observes the late FINAL state.
            read_gatt_char=AsyncMock(side_effect=(b"\x00", b"\x00", b"\x02")),
            write_gatt_char=AsyncMock(side_effect=rejections),
            disconnect=AsyncMock(),
        )
        client = nespresso.NespressoClient(auth_code="0123456789abcdef", mac=address)

        with (
            patch.object(nespresso, "establish_connection", AsyncMock(return_value=connection)),
            patch.object(nespresso.asyncio, "sleep", AsyncMock()),
            self.assertRaises(nespresso.NespressoAuthenticationError),
        ):
            await client.connect(device)

        self.assertEqual(connection.write_gatt_char.await_count, 2)
        self.assertNotIn(
            nespresso.CHAR_UUID_PAIR,
            [awaited.args[0] for awaited in connection.write_gatt_char.await_args_list],
        )
        connection.pair.assert_not_awaited()
        connection.disconnect.assert_awaited_once_with()

    async def test_onboarding_error_is_classified_by_the_failing_write(self) -> None:
        address = "AA:BB:CC:DD:EE:FF"
        device = SimpleNamespace(address=address, name="Expert_1234")

        for failing_write, expected_error in (
            ("tx_level", nespresso.NespressoConnectionError),
            ("auth_code", nespresso.NespressoAuthenticationError),
        ):
            with self.subTest(failing_write=failing_write):
                rejected = nespresso.BleakGATTProtocolError(
                    nespresso.BleakGATTProtocolErrorCode.UNLIKELY_ERROR
                )
                write_effects = (rejected,) if failing_write == "tx_level" else (None, rejected)
                connection = SimpleNamespace(
                    address=address,
                    is_connected=True,
                    pair=AsyncMock(),
                    read_gatt_char=AsyncMock(side_effect=(b"\x00", b"\x00")),
                    write_gatt_char=AsyncMock(side_effect=write_effects),
                    disconnect=AsyncMock(),
                )
                client = nespresso.NespressoClient(mac=address)

                with (
                    patch.object(
                        nespresso, "establish_connection", AsyncMock(return_value=connection)
                    ),
                    patch.object(nespresso.asyncio, "sleep", AsyncMock()),
                    patch.object(client, "generate_auth_key", return_value="0123456789abcdef"),
                    self.assertRaises(expected_error),
                ):
                    await client.connect(device)

                connection.pair.assert_not_awaited()
                connection.disconnect.assert_awaited_once_with()


class ClientSensorSnapshotTests(unittest.IsolatedAsyncioTestCase):
    """Verify polling bypass and atomic cache updates."""

    async def test_zero_interval_reads_every_snapshot(self) -> None:
        address = "AA:BB:CC:DD:EE:FF"
        connection = SimpleNamespace(
            is_connected=True,
            read_gatt_char=AsyncMock(side_effect=(b"\x00\x01", b"\x00\x02")),
        )
        client = nespresso.NespressoClient(scan_interval=0, mac=address)
        client._conn = connection
        client.sensors = {address: [nespresso.CHAR_UUID_NBCAPS]}

        first = await client.get_sensor_data()
        second = await client.get_sensor_data()

        self.assertEqual(first[address]["caps_number"], 1)
        self.assertEqual(second[address]["caps_number"], 2)
        self.assertEqual(connection.read_gatt_char.await_count, 2)

    async def test_authentication_state_read_is_reused_by_the_snapshot(self) -> None:
        address = "AA:BB:CC:DD:EE:FF"
        status = bytes.fromhex("00 02 00 00 00 00 00 00 01")
        connection = SimpleNamespace(
            is_connected=True,
            read_gatt_char=AsyncMock(),
        )
        client = nespresso.NespressoClient(scan_interval=0, mac=address)
        client._conn = connection
        client.sensors = {address: [nespresso.CHAR_UUID_STATE]}
        client._prefetched_sensor_data[nespresso.CHAR_UUID_STATE] = status

        snapshot = await client.get_sensor_data()

        self.assertEqual(snapshot[address]["state"], "READY")
        connection.read_gatt_char.assert_not_awaited()

    async def test_failed_snapshot_does_not_replace_cached_data(self) -> None:
        address = "AA:BB:CC:DD:EE:FF"
        connection = SimpleNamespace(
            is_connected=True,
            read_gatt_char=AsyncMock(side_effect=(b"\x00\x02", OSError("Bluetooth read failed"))),
        )
        client = nespresso.NespressoClient(scan_interval=0, mac=address)
        client._conn = connection
        client.sensors = {address: [nespresso.CHAR_UUID_NBCAPS, nespresso.CHAR_UUID_SLIDER]}
        client.sensordata = {address: {"caps_number": 1}}

        with self.assertRaisesRegex(OSError, "Bluetooth read failed"):
            await client.get_sensor_data()

        self.assertEqual(client.sensordata, {address: {"caps_number": 1}})
        self.assertIsNone(client.data_last_updated)


class ClientRangeAndBufferTests(unittest.IsolatedAsyncioTestCase):
    """Verify service ranges and their exact BLE command payloads."""

    def setUp(self) -> None:
        self.client = nespresso.NespressoClient(
            auth_code="0123456789abcdef", mac="AA:BB:CC:DD:EE:FF"
        )
        self.client._send_command = AsyncMock(return_value=True)

    async def test_capsule_counter_accepts_inclusive_boundaries(self) -> None:
        for value, payload in ((1, b"\x00\x01"), (1000, b"\x03\xe8")):
            with self.subTest(value=value):
                self.client._send_command.reset_mock()

                result = await self.client.update_caps_counter(value)

                self.assertTrue(result)
                self.client._send_command.assert_awaited_once_with(
                    nespresso.CHAR_UUID_NBCAPS, payload, response=False
                )

    async def test_capsule_counter_rejects_values_outside_service_range(self) -> None:
        for value in (0, 1001):
            with self.subTest(value=value), self.assertRaises(ValueError):
                await self.client.update_caps_counter(value)

        self.client._send_command.assert_not_awaited()

    async def test_integer_fields_reject_booleans_and_floats(self) -> None:
        for value in (True, 1.5):
            with self.subTest(value=value), self.assertRaises(TypeError):
                await self.client.update_caps_counter(value)

        self.client._send_command.assert_not_awaited()

    async def test_water_hardness_accepts_inclusive_enum_boundaries(self) -> None:
        for value in (0, 4):
            with self.subTest(value=value):
                self.client._send_command.reset_mock()

                result = await self.client.update_water_hardness(value)

                self.assertTrue(result)
                self.client._send_command.assert_awaited_once_with(
                    nespresso.CHAR_UUID_WATER_HARDNESS,
                    bytes((0xFF, 0xFF, value)),
                    response=False,
                )

    async def test_water_hardness_rejects_values_outside_enum_range(self) -> None:
        for value in (-1, 5):
            with self.subTest(value=value), self.assertRaises(ValueError):
                await self.client.update_water_hardness(value)

        self.client._send_command.assert_not_awaited()

    async def test_predefined_brew_payload(self) -> None:
        machine = machines.CoffeeMachineFactory.get_coffee_machine("Expert_1234", "serial-1")
        self.client.machine = machine
        self.client._conn = SimpleNamespace(address="AA:BB:CC:DD:EE:FF")
        self.client.devices = {self.client._conn.address: machine}
        self.client._send_command = AsyncMock(return_value="Done")

        result = await self.client.brew_predefined(enums.BrewType.AMERICANO, enums.Temperature.HIGH)

        self.assertEqual(result, "Done")
        self.client._send_command.assert_awaited_once_with(
            nespresso.CHAR_UUID_BREW,
            bytes((3, 5, 7, 4, 0, 0, 0, 0, 2, 5)),
            response=True,
        )

    async def test_custom_brew_uses_an_eleven_byte_recipe_payload(self) -> None:
        self.client.machine = machines.CoffeeMachineFactory.get_coffee_machine(
            "Expert_1234", "serial-1"
        )
        self.client._send_command = AsyncMock(side_effect=("Done", "Done"))

        result = await self.client.brew_custom(
            coffee_ml=15, water_ml=300, temp=enums.Temperature.LOW
        )

        self.assertEqual(result, "Done")
        expected_recipe = bytes((1, 16, 8, 0, 0, 1, 0, 15, 2, 1, 44))
        expected_brew = bytes((3, 5, 7, 4, 0, 0, 0, 0, 1, 7))
        self.assertEqual(
            self.client._send_command.await_args_list,
            [
                call(nespresso.CHAR_UUID_BREW, expected_recipe, response=True),
                call(nespresso.CHAR_UUID_BREW, expected_brew, response=True),
            ],
        )

    async def test_custom_brew_rejects_values_outside_service_ranges(self) -> None:
        self.client.machine = machines.CoffeeMachineFactory.get_coffee_machine(
            "Expert_1234", "serial-1"
        )
        invalid_recipes = (
            {"coffee_ml": 14, "water_ml": 100},
            {"coffee_ml": 131, "water_ml": 100},
            {"coffee_ml": 100, "water_ml": 24},
            {"coffee_ml": 100, "water_ml": 301},
        )

        for recipe in invalid_recipes:
            with self.subTest(recipe=recipe), self.assertRaises(ValueError):
                await self.client.brew_custom(**recipe)

        self.client._send_command.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
