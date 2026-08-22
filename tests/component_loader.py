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

    bleak_retry_connector = types.ModuleType("bleak_retry_connector")

    async def establish_connection(*_args, **_kwargs):
        raise AssertionError("establish_connection must be mocked by a test")

    bleak_retry_connector.establish_connection = establish_connection
    bleak_retry_connector.BleakClientWithServiceCache = BleakClientWithServiceCache

    sys.modules["bleak"] = bleak
    sys.modules["bleak.backends"] = bleak_backends
    sys.modules["bleak.backends.device"] = bleak_device
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
