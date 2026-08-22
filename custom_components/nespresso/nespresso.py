"""Bluetooth client for Nespresso coffee machines."""

from __future__ import annotations

import asyncio
import binascii
import secrets
from datetime import datetime, timedelta

from bleak.backends.device import BLEDevice
from bleak.exc import BleakDBusError, BleakGATTProtocolError, BleakGATTProtocolErrorCode
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection

from . import commandResponse
from .enums import BrewType, Ingredient, Temperature
from .machines import (
    CoffeeMachine,
    CoffeeMachineFactory,
    decode_machine_information,
    decode_pairing_key_state,
)
from .machineStatus import BaseDecode


class NespressoError(Exception):
    """Base class for Nespresso client failures."""


class NespressoAuthenticationError(NespressoError):
    """The machine could not be onboarded or authenticated."""


class NespressoConnectionError(NespressoError):
    """A Bluetooth connection could not be established or used."""


class _NespressoCredentialRejected(NespressoAuthenticationError):
    """The machine explicitly rejected an otherwise well-formed credential."""


CHAR_UUID_DEVICE_NAME = "00002a00-0000-1000-8000-00805f9b34fb"
CHAR_UUID_STATE = "06aa3a12-f22a-11e3-9daa-0002a5d5c51b"
CHAR_UUID_NBCAPS = "06aa3a15-f22a-11e3-9daa-0002a5d5c51b"
CHAR_UUID_SLIDER = "06aa3a22-f22a-11e3-9daa-0002a5d5c51b"
CHAR_UUID_WATER_HARDNESS = "06aa3a44-f22a-11e3-9daa-0002a5d5c51b"
CHAR_UUID_AUTH = "06aa3a41-f22a-11e3-9daa-0002a5d5c51b"
CHAR_UUID_ONBOARD_STATUS = "06aa3a51-f22a-11e3-9daa-0002a5d5c51b"
CHAR_UUID_PAIR = "06aa3a61-f22a-11e3-9daa-0002a5d5c51b"
CHAR_UUID_CMDRESP = "06aa3a52-f22a-11e3-9daa-0002a5d5c51b"
CHAR_UUID_SERIAL = "06aa3a31-f22a-11e3-9daa-0002a5d5c51b"
CHAR_UUID_BREW = "06aa3a42-f22a-11e3-9daa-0002a5d5c51b"
CHAR_UUID_INFO = "06aa3a21-f22a-11e3-9daa-0002a5d5c51b"

PAIRING_SETTLE_SECONDS = 2.0
ONBOARDING_SETTLE_SECONDS = 2.0
PAIRING_STATE_POLL_SECONDS = 0.5
PAIRING_STATE_MAX_ATTEMPTS = 5

_LINK_SECURITY_ERRORS = frozenset(
    {
        BleakGATTProtocolErrorCode.INSUFFICIENT_AUTHENTICATION,
        BleakGATTProtocolErrorCode.INSUFFICIENT_AUTHORIZATION,
        BleakGATTProtocolErrorCode.INSUFFICIENT_ENCRYPTION_KEY_SIZE,
        BleakGATTProtocolErrorCode.INSUFFICIENT_ENCRYPTION,
    }
)


def _is_link_security_error(err: Exception) -> bool:
    """Return whether an operation failed because the BLE link is not secured."""

    if isinstance(err, BleakGATTProtocolError):
        return err.code in _LINK_SECURITY_ERRORS
    return bool(
        isinstance(err, BleakDBusError)
        and err.dbus_error == "org.bluez.Error.NotPermitted"
        and "not paired" in (err.dbus_error_details or "").casefold()
    )


sensors_characteristics = (
    CHAR_UUID_STATE,
    CHAR_UUID_NBCAPS,
    CHAR_UUID_SLIDER,
    CHAR_UUID_WATER_HARDNESS,
)

sensor_decoders = {
    CHAR_UUID_STATE: BaseDecode(name="state", format_type="state"),
    CHAR_UUID_NBCAPS: BaseDecode(name="caps_number", format_type="caps_number"),
    CHAR_UUID_SLIDER: BaseDecode(name="slider", format_type="slider"),
    CHAR_UUID_WATER_HARDNESS: BaseDecode(name="water_hardness", format_type="water_hardness"),
}


class NespressoClient:
    """Manage short-lived authenticated connections to one machine."""

    def __init__(
        self,
        scan_interval: timedelta = timedelta(seconds=180),
        auth_code: str | None = None,
        mac: str | None = None,
    ) -> None:
        if isinstance(scan_interval, (int, float)):
            scan_interval = timedelta(seconds=scan_interval)
        if not isinstance(scan_interval, timedelta):
            raise TypeError("scan_interval must be a datetime.timedelta")
        if scan_interval < timedelta(0):
            raise ValueError("scan_interval cannot be negative")

        self.auth_code = auth_code
        self.sensors: dict[str, list[str]] = {}
        self.sensordata: dict[str, dict[str, object]] = {}
        self.devices: dict[str, CoffeeMachine] = {}
        self.data_update_interval = scan_interval
        self.data_update_lock = asyncio.Lock()
        self.data_last_updated: datetime | None = None
        self.command_response: str | None = None
        self.state_response: bytes | bytearray | None = None
        self.is_onboard: bool | None = None
        self.machine: CoffeeMachine | None = None
        self.address = mac
        self._conn: BleakClientWithServiceCache | None = None
        self._prefetched_sensor_data: dict[str, bytes | bytearray] = {}
        self._command_response_event = asyncio.Event()
        self._command_response_error: Exception | None = None
        self._security_pair_attempted = False

    @property
    def isOnboard(self) -> bool | None:
        """Compatibility alias for the previous camel-case attribute."""

        return self.is_onboard

    @isOnboard.setter
    def isOnboard(self, value: bool | None) -> None:
        self.is_onboard = value

    async def connect(self, device: BLEDevice) -> bool:
        """Connect, onboard once if needed, and authenticate the machine."""

        if device is None:
            raise NespressoConnectionError("No Bluetooth device was supplied")

        if self._conn is not None:
            if self._conn.is_connected:
                return True
            await self.disconnect()

        device_address = getattr(device, "address", None)
        device_name = getattr(device, "name", None) or device_address or "Nespresso"
        self._prefetched_sensor_data.clear()
        self._security_pair_attempted = False

        try:
            client = await establish_connection(
                BleakClientWithServiceCache,
                device,
                device_name,
                max_attempts=3,
            )
        except Exception as err:
            raise NespressoConnectionError(
                f"Failed to connect to Nespresso device {device_name}"
            ) from err

        try:
            if not client.is_connected:
                raise NespressoConnectionError(
                    f"Nespresso device {device_name} disconnected during setup"
                )

            if self.auth_code is not None:
                # A saved CMID is authoritative. Try it before inspecting or
                # changing the machine's onboarding state: the status read can
                # briefly report NONE/TEMPORARY, while the saved key is still
                # accepted. Most importantly, never replace a supplied key.
                try:
                    protected_state = await self._authenticate_with_security_retry(
                        client, device_name
                    )
                except _NespressoCredentialRejected:
                    pairing_key_state = await self._stable_pairing_key_state(
                        client, device_name, confirm_absent=True
                    )
                    # Give a valid key a complete second, non-mutating attempt
                    # before any onboarding write. This protects the machine's
                    # limited CMID storage from a delayed protected-read result.
                    await asyncio.sleep(PAIRING_STATE_POLL_SECONDS)
                    try:
                        protected_state = await self._authenticate_with_security_retry(
                            client, device_name
                        )
                    except _NespressoCredentialRejected as err:
                        if pairing_key_state == "PRESENT":
                            raise NespressoAuthenticationError(
                                f"Nespresso device {device_name} rejected the auth code"
                            ) from err
                        # The state can change while the second CMID attempt is
                        # in flight. Reconfirm NONE immediately before the only
                        # mutating fallback so a late FINAL never consumes a
                        # second slot in the machine's limited CMID storage.
                        pairing_key_state = await self._stable_pairing_key_state(
                            client, device_name, confirm_absent=True
                        )
                        if pairing_key_state == "PRESENT":
                            raise NespressoAuthenticationError(
                                f"Nespresso device {device_name} rejected the auth code"
                            ) from err
                        protected_state = await self._onboard_and_authenticate(client, device_name)
                self.is_onboard = True
            else:
                pairing_key_state = await self._stable_pairing_key_state(
                    client, device_name, confirm_absent=True
                )
                if pairing_key_state == "PRESENT":
                    raise NespressoAuthenticationError(
                        f"Nespresso device {device_name} is onboarded but has no auth code"
                    )

                self.auth_code = self.generate_auth_key()
                protected_state = await self._onboard_and_authenticate(client, device_name)

            # Reuse the protected state read as the state sensor value. This
            # verifies authentication without reading the same characteristic
            # a second time during the immediately following coordinator poll.
            self._prefetched_sensor_data[CHAR_UUID_STATE] = protected_state
        except BaseException:
            await self._disconnect_failed_client(client)
            raise

        self._conn = client
        self.address = device_address or client.address
        return True

    async def disconnect(self) -> None:
        """Disconnect the active client; repeated calls are harmless."""

        client = self._conn
        self._conn = None
        if client is None:
            return

        try:
            await client.disconnect()
        except Exception as err:
            raise NespressoConnectionError(
                f"Failed to disconnect Nespresso device {self.address or client.address}"
            ) from err

    @staticmethod
    async def _disconnect_failed_client(client: BleakClientWithServiceCache) -> None:
        """Best-effort cleanup while preserving the original setup exception."""

        try:
            await client.disconnect()
        except Exception:
            pass

    def _require_connection(self) -> BleakClientWithServiceCache:
        client = self._conn
        if client is None or getattr(client, "is_connected", True) is False:
            raise NespressoConnectionError("Nespresso device is not connected")
        return client

    async def get_info(self) -> dict[str, CoffeeMachine]:
        """Read all device information atomically."""

        client = self._require_connection()
        device = await self.load_model()
        address = self.address or client.address
        device.mac_address = address
        device.manufacturer = "Nespresso"
        device.device_name = device.name
        device.paired_status = self.is_onboard

        machine_info = decode_machine_information(await client.read_gatt_char(CHAR_UUID_INFO))
        device.hw_version = machine_info["Hardware Version"]
        device.fw_version = (
            f"{machine_info['Main Firmware Version']}, "
            f"Bootloader: {machine_info['Bootloader Version']}, "
            "Connectivity Firmware: "
            f"{machine_info['Connectivity Firmware Version']}"
        )

        devices = {address: device}
        self.devices = devices
        return devices

    async def get_sensors(self) -> dict[str, list[str]]:
        """Discover supported sensor characteristics for the machine."""

        client = self._require_connection()
        sensor_characteristics: list[str] = []
        for characteristic_uuid in sensors_characteristics:
            characteristic = client.services.get_characteristic(characteristic_uuid)
            if characteristic is not None:
                sensor_characteristics.append(str(characteristic.uuid).lower())

        address = self.address or client.address
        sensors = {address: sensor_characteristics}
        self.sensors = sensors
        return sensors

    async def get_sensor_data(self) -> dict[str, dict[str, object]]:
        """Read a complete sensor snapshot and update the cache on success."""

        async with self.data_update_lock:
            now = datetime.now()
            if (
                self.data_last_updated is not None
                and now - self.data_last_updated < self.data_update_interval
            ):
                return self.sensordata

            client = self._require_connection()
            snapshot: dict[str, dict[str, object]] = {}
            for address, characteristics in self.sensors.items():
                values: dict[str, object] = {}
                for characteristic in characteristics:
                    characteristic_uuid = str(characteristic).lower()
                    decoder = sensor_decoders.get(characteristic_uuid)
                    if decoder is None:
                        raise NespressoError(
                            f"No decoder is available for sensor {characteristic_uuid}"
                        )
                    raw_data = self._prefetched_sensor_data.pop(characteristic_uuid, None)
                    if raw_data is None:
                        raw_data = await client.read_gatt_char(characteristic_uuid)
                    values.update(decoder.decode_data(raw_data))
                snapshot[address] = values

            self.sensordata = snapshot
            self.data_last_updated = datetime.now()
            return snapshot

    async def get_onboard_status(self, client: BleakClientWithServiceCache) -> bool:
        """Read and remember whether a pairing key is present."""

        pairing_key_state = await self.get_pairing_key_state(client)
        self.is_onboard = pairing_key_state == "PRESENT"
        return self.is_onboard

    async def get_pairing_key_state(self, client: BleakClientWithServiceCache) -> str:
        """Read the complete pairing-key state reported by the machine."""

        onboard_status = await client.read_gatt_char(CHAR_UUID_ONBOARD_STATUS)
        if not onboard_status:
            raise NespressoConnectionError("The machine returned no onboarding state")

        try:
            pairing_key_state = decode_pairing_key_state(onboard_status)
        except ValueError as err:
            raise NespressoConnectionError(
                "The machine returned an invalid onboarding state"
            ) from err
        if pairing_key_state == "UNDEFINED":
            raise NespressoConnectionError("The machine returned an undefined onboarding state")

        return pairing_key_state

    async def _pair_for_link_security(
        self, client: BleakClientWithServiceCache, device_name: str
    ) -> None:
        """Use OS pairing once as a fallback for machines requiring encryption."""

        if self._security_pair_attempted:
            return

        self._security_pair_attempted = True
        try:
            await client.pair()
            await asyncio.sleep(PAIRING_SETTLE_SECONDS)
        except Exception as err:
            raise NespressoConnectionError(
                f"Failed to establish a secure Bluetooth link to {device_name}"
            ) from err

    async def _pairing_key_state_with_security_retry(
        self, client: BleakClientWithServiceCache, device_name: str
    ) -> str:
        """Read pairing state, retrying once after link-security negotiation."""

        try:
            return await self.get_pairing_key_state(client)
        except NespressoConnectionError:
            raise
        except Exception as err:
            if _is_link_security_error(err) and not self._security_pair_attempted:
                await self._pair_for_link_security(client, device_name)
                try:
                    return await self.get_pairing_key_state(client)
                except NespressoConnectionError:
                    raise
                except Exception as retry_err:
                    raise NespressoConnectionError(
                        f"Failed to read onboarding state from {device_name}"
                    ) from retry_err
            raise NespressoConnectionError(
                f"Failed to read onboarding state from {device_name}"
            ) from err

    async def _stable_pairing_key_state(
        self,
        client: BleakClientWithServiceCache,
        device_name: str,
        *,
        confirm_absent: bool,
    ) -> str:
        """Wait for a non-temporary state and optionally confirm NONE twice."""

        pairing_key_state = await self._pairing_key_state_with_security_retry(client, device_name)
        attempts_remaining = PAIRING_STATE_MAX_ATTEMPTS
        absent_reads = 0

        while True:
            if pairing_key_state == "PRESENT":
                return pairing_key_state
            if pairing_key_state == "ABSENT":
                absent_reads += 1
                if not confirm_absent or absent_reads >= 2:
                    return pairing_key_state
            else:
                absent_reads = 0

            if attempts_remaining == 0:
                raise NespressoConnectionError(
                    f"Nespresso device {device_name} remained in a temporary onboarding state"
                )
            attempts_remaining -= 1
            await asyncio.sleep(PAIRING_STATE_POLL_SECONDS)
            pairing_key_state = await self._pairing_key_state_with_security_retry(
                client, device_name
            )

    async def _wait_for_onboarding(
        self, client: BleakClientWithServiceCache, device_name: str
    ) -> None:
        """Wait until a newly written pairing key becomes permanent."""

        await asyncio.sleep(ONBOARDING_SETTLE_SECONDS)
        for attempt in range(PAIRING_STATE_MAX_ATTEMPTS):
            pairing_key_state = await self._pairing_key_state_with_security_retry(
                client, device_name
            )
            if pairing_key_state == "PRESENT":
                self.is_onboard = True
                return
            if attempt + 1 < PAIRING_STATE_MAX_ATTEMPTS:
                await asyncio.sleep(PAIRING_STATE_POLL_SECONDS)

        raise NespressoAuthenticationError(
            f"Nespresso device {device_name} did not accept onboarding"
        )

    async def _authenticate_once(
        self, client: BleakClientWithServiceCache, device_name: str
    ) -> bytes | bytearray:
        """Write the CMID and verify it with one protected read."""

        try:
            await self.auth(client)
        except BleakGATTProtocolError as err:
            if err.code == BleakGATTProtocolErrorCode.UNLIKELY_ERROR:
                raise _NespressoCredentialRejected(
                    f"Nespresso device {device_name} rejected the auth-code write"
                ) from err
            raise

        try:
            protected_state = await client.read_gatt_char(CHAR_UUID_STATE)
        except BleakGATTProtocolError as err:
            if err.code == BleakGATTProtocolErrorCode.READ_NOT_PERMITTED:
                raise _NespressoCredentialRejected(
                    f"Nespresso device {device_name} rejected the auth code"
                ) from err
            raise

        if not protected_state:
            raise NespressoConnectionError(
                f"Nespresso device {device_name} returned no protected state"
            )
        return protected_state

    async def _authenticate_with_security_retry(
        self, client: BleakClientWithServiceCache, device_name: str
    ) -> bytes | bytearray:
        """Authenticate, using OS pairing only after a link-security error."""

        try:
            return await self._authenticate_once(client, device_name)
        except _NespressoCredentialRejected:
            raise
        except NespressoAuthenticationError:
            raise
        except NespressoConnectionError:
            raise
        except Exception as err:
            if _is_link_security_error(err) and not self._security_pair_attempted:
                await self._pair_for_link_security(client, device_name)
                try:
                    return await self._authenticate_once(client, device_name)
                except _NespressoCredentialRejected:
                    raise
                except NespressoAuthenticationError:
                    raise
                except NespressoConnectionError:
                    raise
                except Exception as retry_err:
                    raise NespressoConnectionError(
                        f"Bluetooth authentication transport failed for {device_name}"
                    ) from retry_err
            raise NespressoConnectionError(
                f"Bluetooth authentication transport failed for {device_name}"
            ) from err

    async def _onboard_with_security_retry(
        self, client: BleakClientWithServiceCache, device_name: str
    ) -> None:
        """Install the selected CMID, retrying only for link-security errors."""

        auth_bytes = self._auth_bytes(self.auth_code)
        for attempt in range(2):
            try:
                await client.write_gatt_char(CHAR_UUID_PAIR, bytearray([1]), response=True)
            except Exception as err:
                if (
                    attempt == 0
                    and _is_link_security_error(err)
                    and not self._security_pair_attempted
                ):
                    await self._pair_for_link_security(client, device_name)
                    continue
                raise NespressoConnectionError(
                    f"Failed to set pairing power for {device_name}"
                ) from err

            try:
                await client.write_gatt_char(CHAR_UUID_AUTH, auth_bytes, response=True)
            except BleakGATTProtocolError as err:
                if err.code == BleakGATTProtocolErrorCode.UNLIKELY_ERROR:
                    raise NespressoAuthenticationError(
                        f"Nespresso device {device_name} rejected onboarding"
                    ) from err
                if (
                    attempt == 0
                    and _is_link_security_error(err)
                    and not self._security_pair_attempted
                ):
                    await self._pair_for_link_security(client, device_name)
                    continue
                raise NespressoConnectionError(
                    f"Bluetooth onboarding transport failed for {device_name}"
                ) from err
            except Exception as err:
                if (
                    attempt == 0
                    and _is_link_security_error(err)
                    and not self._security_pair_attempted
                ):
                    await self._pair_for_link_security(client, device_name)
                    continue
                raise NespressoConnectionError(
                    f"Bluetooth onboarding transport failed for {device_name}"
                ) from err
            return

        raise NespressoConnectionError(f"Bluetooth onboarding transport failed for {device_name}")

    async def _onboard_and_authenticate(
        self, client: BleakClientWithServiceCache, device_name: str
    ) -> bytes | bytearray:
        """Install the current CMID, wait for FINAL, and authenticate it."""

        await self._onboard_with_security_retry(client, device_name)
        await self._wait_for_onboarding(client, device_name)
        try:
            return await self._authenticate_with_security_retry(client, device_name)
        except _NespressoCredentialRejected as err:
            raise NespressoAuthenticationError(
                f"Nespresso device {device_name} rejected the onboarded auth code"
            ) from err

    async def load_model(self) -> CoffeeMachine:
        """Read the model name and serial number."""

        client = self._require_connection()
        serial = (await client.read_gatt_char(CHAR_UUID_SERIAL)).decode("utf-8").rstrip("\x00")
        device_name = (
            (await client.read_gatt_char(CHAR_UUID_DEVICE_NAME)).decode("utf-8").rstrip("\x00")
        )
        self.machine = CoffeeMachineFactory.get_coffee_machine(device_name, serial)
        return self.machine

    @staticmethod
    def _auth_bytes(auth_code: str | None) -> bytes:
        if not isinstance(auth_code, str) or len(auth_code) != 16:
            raise NespressoAuthenticationError(
                "The Nespresso auth code must contain exactly 16 hexadecimal characters"
            )
        try:
            return binascii.unhexlify(auth_code)
        except (binascii.Error, ValueError) as err:
            raise NespressoAuthenticationError(
                "The Nespresso auth code is not valid hexadecimal"
            ) from err

    async def auth(self, client: BleakClientWithServiceCache) -> None:
        """Write the configured authentication key."""

        await client.write_gatt_char(
            CHAR_UUID_AUTH, self._auth_bytes(self.auth_code), response=True
        )

    async def onboard(self, client: BleakClientWithServiceCache) -> None:
        """Install the selected authentication key on the machine."""

        auth_bytes = self._auth_bytes(self.auth_code)
        await client.write_gatt_char(CHAR_UUID_PAIR, bytearray([1]), response=True)
        await client.write_gatt_char(CHAR_UUID_AUTH, auth_bytes, response=True)

    def notification_handler(self, sender: object, data: bytearray) -> None:
        """Handle a command response notification."""

        del sender
        try:
            self.command_response = commandResponse.from_byte_buffer(data).value
        except Exception as err:
            self._command_response_error = err
        finally:
            self._command_response_event.set()

    def state_notification_handler(self, sender: object, data: bytearray) -> None:
        """Handle a state notification."""

        del sender
        self.state_response = data

    @staticmethod
    def generate_auth_key() -> str:
        """Generate the eight-byte key format expected by the machine."""

        return secrets.token_hex(8)

    def _require_machine(self) -> CoffeeMachine:
        if self.machine is None:
            raise NespressoError("Machine information has not been loaded")
        return self.machine

    @staticmethod
    def _validate_temperature(temp: Temperature) -> None:
        if not isinstance(temp, Temperature):
            raise TypeError("temp must be a Temperature value")

    async def brew_predefined(
        self,
        brew: BrewType = BrewType.RISTRETTO,
        temp: Temperature = Temperature.MEDIUM,
    ) -> str | bool:
        """Start one of the machine's predefined recipes."""

        machine = self._require_machine()
        if not isinstance(brew, BrewType):
            raise TypeError("brew must be a BrewType value")
        self._validate_temperature(temp)
        if machine.model is None or not brew.is_brew_applicable_for_machine(machine.model):
            model_name = machine.model.name if machine.model else machine.name
            raise ValueError(f"{brew.name} is not valid for {model_name}")

        command = bytearray(10)
        command[0:4] = bytes((3, 5, 7, 4))
        command[8] = (
            temp.value
            if machine.configurations["temperature_control"]
            else Temperature.MEDIUM.value
        )
        command[9] = brew.value
        return await self._send_command(CHAR_UUID_BREW, command, response=True)

    async def brew_custom(
        self,
        coffee_ml: int = 100,
        water_ml: int = 100,
        temp: Temperature = Temperature.MEDIUM,
    ) -> str | bool:
        """Configure and start a custom coffee-and-water recipe."""

        machine = self._require_machine()
        if not machine.configurations["custom_recipes"]:
            raise NespressoError(f"Custom recipes are not supported for {machine.name}")
        self._validate_temperature(temp)
        self._validate_int_range("coffee_ml", coffee_ml, 15, 130)
        self._validate_int_range("water_ml", water_ml, 25, 300)

        preparation = bytearray(11)
        preparation[0:3] = bytes((1, 16, 8))
        preparation[5] = Ingredient.COFFEE.value
        preparation[6:8] = coffee_ml.to_bytes(2, byteorder="big")
        preparation[8] = Ingredient.WATER.value
        preparation[9:11] = water_ml.to_bytes(2, byteorder="big")

        preparation_response = await self._send_command(CHAR_UUID_BREW, preparation, response=True)
        if preparation_response != commandResponse.CommandResponse.DONE.value:
            return preparation_response

        command = bytearray(10)
        command[0:4] = bytes((3, 5, 7, 4))
        command[8] = (
            temp.value
            if machine.configurations["temperature_control"]
            else Temperature.MEDIUM.value
        )
        command[9] = BrewType.CUSTOM.value
        return await self._send_command(CHAR_UUID_BREW, command, response=True)

    @staticmethod
    def _validate_int_range(name: str, value: int, minimum: int, maximum: int) -> None:
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"{name} must be an integer")
        if not minimum <= value <= maximum:
            raise ValueError(f"{name} must be between {minimum} and {maximum}")

    async def update_caps_counter(self, caps: int) -> str | bool:
        """Set the remaining-capsule counter."""

        self._validate_int_range("caps", caps, 1, 1000)
        return await self._send_command(
            CHAR_UUID_NBCAPS,
            caps.to_bytes(2, byteorder="big"),
            response=False,
        )

    async def update_water_hardness(self, level: int) -> str | bool:
        """Set the configured water-hardness level."""

        self._validate_int_range("level", level, 0, 4)
        command = bytearray((0xFF, 0xFF, level))
        return await self._send_command(CHAR_UUID_WATER_HARDNESS, command, response=False)

    async def _send_command(
        self,
        characteristic: str,
        command: bytes | bytearray,
        response: bool = False,
    ) -> str | bool:
        """Write a command, optionally waiting for its notification response."""

        client = self._require_connection()
        if not response:
            await client.write_gatt_char(characteristic, command, response=False)
            return True

        self.command_response = None
        self._command_response_error = None
        self._command_response_event.clear()
        notification_started = False
        try:
            await client.start_notify(CHAR_UUID_CMDRESP, self.notification_handler)
            notification_started = True

            for _attempt in range(3):
                self._command_response_event.clear()
                await client.write_gatt_char(characteristic, command, response=True)
                try:
                    await asyncio.wait_for(self._command_response_event.wait(), timeout=5)
                except TimeoutError:
                    continue

                if self._command_response_error is not None:
                    raise NespressoError(
                        "Invalid command response"
                    ) from self._command_response_error
                if self.command_response is not None:
                    return self.command_response

            raise NespressoError("No command response received after three attempts")
        finally:
            if notification_started:
                await client.stop_notify(CHAR_UUID_CMDRESP)
