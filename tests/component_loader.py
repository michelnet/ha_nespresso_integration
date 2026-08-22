"""Load integration modules without importing Home Assistant.

Importing ``custom_components.nespresso`` executes its Home Assistant dependent
``__init__`` module.  The protocol and Bluetooth client modules do not need Home
Assistant, so the test suite exposes the component directory as a small private
package instead.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from enum import IntEnum
from pathlib import Path

COMPONENT_ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "nespresso"
TEST_PACKAGE = "_nespresso_component_under_test"


def _install_test_package() -> None:
    """Install a namespace package pointing at the integration source."""
    if TEST_PACKAGE in sys.modules:
        return

    package = types.ModuleType(TEST_PACKAGE)
    package.__path__ = [str(COMPONENT_ROOT)]
    package.__package__ = TEST_PACKAGE
    sys.modules[TEST_PACKAGE] = package


def _install_bluetooth_stubs() -> None:
    """Provide the tiny Bleak surface needed to import the client module."""
    bleak = types.ModuleType("bleak")

    class BleakClient:
        """Import-only stand-in for bleak.BleakClient."""

    class BleakScanner:
        """Import-only stand-in for bleak.BleakScanner."""

    class BLEDevice:
        """Import-only stand-in for bleak.backends.device.BLEDevice."""

    class BleakClientWithServiceCache:
        """Import-only stand-in for bleak-retry-connector's client type."""

    bleak.BLEDevice = BLEDevice
    bleak.BleakClient = BleakClient
    bleak.BleakScanner = BleakScanner

    bleak_backends = types.ModuleType("bleak.backends")
    bleak_backends.__path__ = []
    bleak_device = types.ModuleType("bleak.backends.device")
    bleak_device.BLEDevice = BLEDevice

    bleak_exc = types.ModuleType("bleak.exc")

    class BleakError(Exception):
        """Import-only stand-in for the base Bleak exception."""

    class BleakGATTProtocolErrorCode(IntEnum):
        """ATT error codes used by the client tests."""

        READ_NOT_PERMITTED = 0x02
        INSUFFICIENT_AUTHENTICATION = 0x05
        INSUFFICIENT_AUTHORIZATION = 0x08
        INSUFFICIENT_ENCRYPTION_KEY_SIZE = 0x0C
        UNLIKELY_ERROR = 0x0E
        INSUFFICIENT_ENCRYPTION = 0x0F

    class BleakGATTProtocolError(BleakError):
        """Import-only stand-in for Bleak 3's structured ATT exception."""

        def __init__(self, error_code: int) -> None:
            super().__init__(error_code)

        @property
        def code(self) -> BleakGATTProtocolErrorCode:
            return BleakGATTProtocolErrorCode(self.args[0])

    class BleakDBusError(BleakError):
        """Import-only stand-in for Bleak's structured BlueZ exception."""

        def __init__(self, dbus_error: str, error_body: list[object]) -> None:
            super().__init__(dbus_error, *error_body)

        @property
        def dbus_error(self) -> str:
            return self.args[0]

        @property
        def dbus_error_details(self) -> str | None:
            return self.args[1] if len(self.args) > 1 else None

    bleak_exc.BleakError = BleakError
    bleak_exc.BleakDBusError = BleakDBusError
    bleak_exc.BleakGATTProtocolError = BleakGATTProtocolError
    bleak_exc.BleakGATTProtocolErrorCode = BleakGATTProtocolErrorCode

    bleak_retry_connector = types.ModuleType("bleak_retry_connector")

    async def establish_connection(*_args, **_kwargs):
        raise AssertionError("establish_connection must be mocked by a test")

    bleak_retry_connector.establish_connection = establish_connection
    bleak_retry_connector.BleakClientWithServiceCache = BleakClientWithServiceCache

    sys.modules["bleak"] = bleak
    sys.modules["bleak.backends"] = bleak_backends
    sys.modules["bleak.backends.device"] = bleak_device
    sys.modules["bleak.exc"] = bleak_exc
    sys.modules["bleak_retry_connector"] = bleak_retry_connector


def load_component_module(module_name: str):
    """Return one component module loaded below the private test package."""
    _install_test_package()
    if module_name == "nespresso":
        _install_bluetooth_stubs()

    qualified_name = f"{TEST_PACKAGE}.{module_name}"
    if qualified_name in sys.modules:
        return sys.modules[qualified_name]

    module_path = COMPONENT_ROOT / f"{module_name}.py"
    spec = importlib.util.spec_from_file_location(qualified_name, module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load {module_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[qualified_name] = module
    spec.loader.exec_module(module)
    return module
