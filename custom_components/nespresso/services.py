"""Service actions for the Nespresso integration."""

from __future__ import annotations

import logging
from typing import NoReturn, cast

import voluptuous as vol
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_DEVICE_ID
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr

from .const import (
    ATTR_BREW_TEMPERATURE,
    ATTR_BREW_TYPE,
    ATTR_CAPS,
    ATTR_COFFEE_ML,
    ATTR_WATER_ML,
    DEFAULT_BREW_TEMPERATURE,
    DEFAULT_BREW_TYPE,
    DOMAIN,
    SERVICE_CAPS,
    SERVICE_COFFEE,
)
from .coordinator import NespressoConfigEntry, NespressoDataUpdateCoordinator
from .machines import BrewType, Temperature

_LOGGER = logging.getLogger(__name__)

_BREW_TYPE_NAMES = tuple(brew.name.lower() for brew in BrewType if brew is not BrewType.CUSTOM)
_TEMPERATURE_NAMES = tuple(temperature.name.lower() for temperature in Temperature)

_NORMALIZED_BREW_TYPE = vol.All(cv.string, lambda value: value.lower(), vol.In(_BREW_TYPE_NAMES))
_NORMALIZED_TEMPERATURE = vol.All(
    cv.string, lambda value: value.lower(), vol.In(_TEMPERATURE_NAMES)
)

COFFEE_SERVICE_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_DEVICE_ID): cv.string,
        vol.Optional(
            ATTR_BREW_TEMPERATURE, default=DEFAULT_BREW_TEMPERATURE
        ): _NORMALIZED_TEMPERATURE,
        vol.Optional(ATTR_BREW_TYPE, default=DEFAULT_BREW_TYPE): _NORMALIZED_BREW_TYPE,
        vol.Optional(ATTR_COFFEE_ML): vol.All(vol.Coerce(int), vol.Range(min=15, max=130)),
        vol.Optional(ATTR_WATER_ML): vol.All(vol.Coerce(int), vol.Range(min=25, max=300)),
    }
)

CAPS_SERVICE_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_DEVICE_ID): cv.string,
        vol.Required(ATTR_CAPS): vol.All(vol.Coerce(int), vol.Range(min=1, max=1000)),
    }
)


@callback
def _async_target(hass: HomeAssistant, device_id: str | None) -> NespressoDataUpdateCoordinator:
    """Resolve a service target to a loaded Nespresso coordinator."""
    if device_id is not None:
        device_registry = dr.async_get(hass)
        if (device_entry := device_registry.async_get(device_id)) is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_device_id",
                translation_placeholders={"device_id": device_id},
            )

        entry = hass.config_entries.async_get_entry(device_entry.config_entry_id)
        if entry is None or entry.domain != DOMAIN:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="device_not_belonging",
                translation_placeholders={"device_id": device_id},
            )
        if entry.state is not ConfigEntryState.LOADED:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="device_entry_not_loaded",
                translation_placeholders={"device_id": device_id},
            )
        return cast(NespressoConfigEntry, entry).runtime_data

    # Compatibility for automations created before 0.2.0. This remains
    # deterministic for the common single-machine installation.
    loaded_entries = [
        entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.state is ConfigEntryState.LOADED
    ]
    if len(loaded_entries) != 1:
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="device_required")
    return cast(NespressoConfigEntry, loaded_entries[0]).runtime_data


def _raise_action_failed(error: object) -> NoReturn:
    """Raise a translated action error."""
    raise HomeAssistantError(
        translation_domain=DOMAIN,
        translation_key="action_failed",
        translation_placeholders={"error": str(error)},
    )


async def async_handle_coffee(call: ServiceCall) -> None:
    """Handle the coffee action."""
    coffee_ml: int | None = call.data.get(ATTR_COFFEE_ML)
    water_ml: int | None = call.data.get(ATTR_WATER_ML)
    if (coffee_ml is None) != (water_ml is None):
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="missing_custom_volume"
        )

    coordinator = _async_target(call.hass, call.data.get(ATTR_DEVICE_ID))
    brew_type = BrewType[call.data[ATTR_BREW_TYPE].upper()]
    temperature = Temperature[call.data[ATTR_BREW_TEMPERATURE].upper()]

    try:
        response = await coordinator.async_brew(brew_type, temperature, coffee_ml, water_ml)
    except Exception as err:
        _LOGGER.debug("Nespresso coffee action failed", exc_info=True)
        _raise_action_failed(err)

    if response not in (True, "Done"):
        _raise_action_failed(response or "No response from the machine")


async def async_handle_caps(call: ServiceCall) -> None:
    """Handle the capsule-counter action."""
    coordinator = _async_target(call.hass, call.data.get(ATTR_DEVICE_ID))
    try:
        response = await coordinator.async_set_capsule_count(call.data[ATTR_CAPS])
    except Exception as err:
        _LOGGER.debug("Nespresso capsule action failed", exc_info=True)
        _raise_action_failed(err)

    if response is not True:
        _raise_action_failed("No response from the machine")


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register integration-wide actions once."""
    if not hass.services.has_service(DOMAIN, SERVICE_COFFEE):
        hass.services.async_register(
            DOMAIN,
            SERVICE_COFFEE,
            async_handle_coffee,
            schema=COFFEE_SERVICE_SCHEMA,
        )
    if not hass.services.has_service(DOMAIN, SERVICE_CAPS):
        hass.services.async_register(
            DOMAIN,
            SERVICE_CAPS,
            async_handle_caps,
            schema=CAPS_SERVICE_SCHEMA,
        )
