"""Sensor entities for Nespresso Bluetooth machines."""

from __future__ import annotations

import logging
from enum import Enum
from typing import override

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import NespressoConfigEntry, NespressoDataUpdateCoordinator, SensorValue

_LOGGER = logging.getLogger(__name__)

MACHINE_STATE_OPTIONS = [
    "reset",
    "heat_up",
    "ready",
    "descaling_ready",
    "brewing",
    "advanced_selection_menu",
    "descaling",
    "steam_out",
    "error",
    "power_save",
    "over_heat",
    "diagnostic_mode",
    "ble_settings",
    "factory_reset",
    "water_hardness_settings",
    "stand_by_delay_settings",
    "unknown",
]

SENSOR_DESCRIPTIONS: tuple[SensorEntityDescription, ...] = (
    SensorEntityDescription(
        key="state",
        translation_key="state",
        device_class=SensorDeviceClass.ENUM,
        options=MACHINE_STATE_OPTIONS,
        icon="mdi:coffee-maker",
    ),
    SensorEntityDescription(
        key="water_is_empty",
        translation_key="water_is_empty",
        device_class=SensorDeviceClass.ENUM,
        options=["not_empty", "empty"],
        icon="mdi:water-off",
    ),
    SensorEntityDescription(
        key="descaling_needed",
        translation_key="descaling_needed",
        device_class=SensorDeviceClass.ENUM,
        options=["not_needed", "needed"],
        icon="mdi:coffee-maker-check",
    ),
    SensorEntityDescription(
        key="capsule_mechanism_jammed",
        translation_key="capsule_mechanism_jammed",
        device_class=SensorDeviceClass.ENUM,
        options=["not_jammed", "jammed"],
        icon="mdi:alert-circle-outline",
    ),
    SensorEntityDescription(
        key="water_fresh",
        translation_key="water_fresh",
        device_class=SensorDeviceClass.ENUM,
        options=["not_fresh", "fresh"],
        icon="mdi:water-check",
    ),
    SensorEntityDescription(
        key="descaling_counter",
        translation_key="descaling_counter",
        icon="mdi:counter",
    ),
    SensorEntityDescription(
        key="caps_number",
        translation_key="caps_number",
        icon="mdi:coffee-outline",
    ),
    SensorEntityDescription(
        key="slider",
        translation_key="slider",
        device_class=SensorDeviceClass.ENUM,
        options=["open", "closed"],
        icon="mdi:door-sliding",
    ),
    SensorEntityDescription(
        key="water_hardness",
        translation_key="water_hardness",
        device_class=SensorDeviceClass.ENUM,
        options=["level_0", "level_1", "level_2", "level_3", "level_4"],
        icon="mdi:water-percent",
    ),
)


async def async_setup_entry(
    _hass: HomeAssistant,
    entry: NespressoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up sensors for a Nespresso config entry."""
    coordinator = entry.runtime_data
    available_keys = set(coordinator.data)
    unknown_keys = available_keys.difference(description.key for description in SENSOR_DESCRIPTIONS)
    if unknown_keys:
        _LOGGER.debug("Ignoring unsupported Nespresso sensor keys: %s", unknown_keys)

    async_add_entities(
        NespressoSensor(coordinator, description)
        for description in SENSOR_DESCRIPTIONS
        if description.key in available_keys
    )


class NespressoSensor(CoordinatorEntity[NespressoDataUpdateCoordinator], SensorEntity):
    """Representation of one Nespresso data point."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: NespressoDataUpdateCoordinator,
        description: SensorEntityDescription,
    ) -> None:
        """Initialize a coordinator-backed sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.address}_{description.key}"

        machine = coordinator.machine
        assert machine is not None
        self._attr_device_info = DeviceInfo(
            connections={(dr.CONNECTION_BLUETOOTH, coordinator.address)},
            identifiers={(DOMAIN, coordinator.address)},
            manufacturer="Nespresso",
            name=machine.name,
            model=(
                machine.model.name.replace("_", " ").title()
                if machine.model is not None
                else machine.name
            ),
            serial_number=machine.serial,
            sw_version=machine.fw_version,
            hw_version=machine.hw_version,
        )

    @property
    @override
    def native_value(self) -> SensorValue:
        """Return the latest native sensor value."""
        value = self.coordinator.data.get(self.entity_description.key)
        if isinstance(value, Enum):
            return value.name.lower()
        if isinstance(value, str):
            return value.lower()
        return value
