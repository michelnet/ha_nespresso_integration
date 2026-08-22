"""Data coordinator for Nespresso Bluetooth machines."""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from datetime import timedelta
from typing import override

from homeassistant.components.bluetooth import async_ble_device_from_address
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, CONF_TOKEN
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, SCAN_INTERVAL
from .machines import BrewType, CoffeeMachine, Temperature
from .nespresso import (
    NespressoAuthenticationError,
    NespressoClient,
    NespressoConnectionError,
)

_LOGGER = logging.getLogger(__name__)

type SensorValue = bool | int | float | str | bytes | None
type NespressoData = dict[str, SensorValue]
type NespressoConfigEntry = ConfigEntry[NespressoDataUpdateCoordinator]


class NespressoDataUpdateCoordinator(DataUpdateCoordinator[NespressoData]):
    """Coordinate one serialized Bluetooth session per machine."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the coordinator."""
        self.address: str = entry.data[CONF_ADDRESS]
        self.client = NespressoClient(
            # The coordinator owns update scheduling. Disable the client's
            # compatibility cache so every coordinator refresh performs a real
            # sensor read instead of occasionally returning a 60-second-old
            # snapshot after an early/staggered timer callback.
            scan_interval=timedelta(0),
            auth_code=entry.data.get(CONF_TOKEN),
            mac=self.address,
        )
        self.machine: CoffeeMachine | None = None
        self._operation_lock = asyncio.Lock()

        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}-{self.address}",
            update_interval=SCAN_INTERVAL,
            always_update=False,
        )

    async def _async_connect(self) -> None:
        """Connect using Home Assistant's best available Bluetooth path."""
        ble_device = async_ble_device_from_address(self.hass, self.address, connectable=True)
        if ble_device is None:
            raise NespressoConnectionError(
                f"Bluetooth device {self.address} is not currently available"
            )
        if not await self.client.connect(ble_device):
            raise NespressoConnectionError(f"Unable to connect to Bluetooth device {self.address}")

    async def _async_initialize_machine(self) -> None:
        """Read static machine information and discover readable sensors."""
        devices = await self.client.get_info()
        if not devices:
            raise NespressoConnectionError("The machine returned no device information")

        machine = next(iter(devices.values()))
        if machine.model is None:
            raise ConfigEntryError(f"Unsupported Nespresso machine model: {machine.name}")
        await self.client.get_sensors()
        self.machine = machine

    @override
    async def _async_update_data(self) -> NespressoData:
        """Fetch every sensor in one Bluetooth transaction."""
        async with self._operation_lock:
            try:
                await self._async_connect()
                if self.machine is None:
                    await self._async_initialize_machine()

                sensor_data = await self.client.get_sensor_data()
                values = next(iter(sensor_data.values()), None)
                if not values:
                    raise NespressoConnectionError("The machine returned no sensor data")
                return dict(values)
            except NespressoAuthenticationError as err:
                raise ConfigEntryAuthFailed from err
            except ConfigEntryError:
                raise
            except NespressoConnectionError as err:
                raise UpdateFailed(str(err)) from err
            except Exception as err:
                raise UpdateFailed(f"Unexpected Bluetooth error: {err}") from err
            finally:
                with suppress(Exception):
                    await self.client.disconnect()

    async def async_brew(
        self,
        brew_type: BrewType,
        temperature: Temperature,
        coffee_ml: int | None = None,
        water_ml: int | None = None,
    ) -> str | bool | None:
        """Prepare a predefined or custom beverage."""
        async with self._operation_lock:
            try:
                await self._async_connect()
                if self.machine is None:
                    await self._async_initialize_machine()
                if coffee_ml is not None and water_ml is not None:
                    return await self.client.brew_custom(
                        coffee_ml=coffee_ml,
                        water_ml=water_ml,
                        temp=temperature,
                    )
                return await self.client.brew_predefined(brew=brew_type, temp=temperature)
            finally:
                with suppress(Exception):
                    await self.client.disconnect()

    async def async_set_capsule_count(self, caps: int) -> bool | None:
        """Set the machine's capsule counter and publish the new value."""
        async with self._operation_lock:
            try:
                await self._async_connect()
                response = await self.client.update_caps_counter(caps)
            finally:
                with suppress(Exception):
                    await self.client.disconnect()

        if response:
            updated_data = dict(self.data)
            updated_data["caps_number"] = caps
            self.async_set_updated_data(updated_data)
        return response
