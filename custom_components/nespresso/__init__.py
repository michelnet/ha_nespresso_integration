"""The Nespresso Bluetooth integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN, SENSOR_KEYS
from .coordinator import NespressoConfigEntry, NespressoDataUpdateCoordinator
from .services import async_setup_services

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)
PLATFORMS: tuple[Platform, ...] = (Platform.SENSOR,)


async def async_setup(hass: HomeAssistant, _config: ConfigType) -> bool:
    """Set up integration-wide Nespresso actions."""
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: NespressoConfigEntry) -> bool:
    """Set up Nespresso from a config entry."""
    coordinator = NespressoDataUpdateCoordinator(hass, entry)
    entry.runtime_data = coordinator

    # Raise setup failures here so Home Assistant can retry the complete config
    # entry instead of loading an empty entity platform.
    await coordinator.async_config_entry_first_refresh()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: NespressoConfigEntry) -> bool:
    """Unload a Nespresso config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate legacy display-name-based entity unique IDs to address-based IDs."""
    _LOGGER.debug("Migrating Nespresso config entry from version %s", entry.version)

    if entry.version > 2:
        _LOGGER.error("Cannot migrate unsupported config entry version %s", entry.version)
        return False

    if entry.version == 1:
        address: str = entry.data[CONF_ADDRESS]
        entity_registry = er.async_get(hass)
        registry_entries = er.async_entries_for_config_entry(entity_registry, entry.entry_id)

        for registry_entry in registry_entries:
            for sensor_key in SENSOR_KEYS:
                new_unique_id = f"{address}_{sensor_key}"
                if registry_entry.unique_id == new_unique_id:
                    break
                if registry_entry.unique_id.endswith(f"-{sensor_key}"):
                    entity_registry.async_update_entity(
                        registry_entry.entity_id, new_unique_id=new_unique_id
                    )
                    break

        hass.config_entries.async_update_entry(entry, version=2)

    return True
