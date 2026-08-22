"""Diagnostics support for the Nespresso integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_ADDRESS, CONF_TOKEN
from homeassistant.core import HomeAssistant

from .coordinator import NespressoConfigEntry

TO_REDACT = {
    CONF_ADDRESS,
    CONF_TOKEN,
    "name",
    "serial_number",
    "title",
    "unique_id",
}


async def async_get_config_entry_diagnostics(
    _hass: HomeAssistant, entry: NespressoConfigEntry
) -> dict[str, Any]:
    """Return privacy-safe diagnostics for a config entry."""
    coordinator = entry.runtime_data
    machine = coordinator.machine

    device = None
    if machine is not None:
        device = {
            "name": machine.name,
            "model": machine.model.name if machine.model is not None else machine.name,
            "serial_number": machine.serial,
            "firmware_version": machine.fw_version,
            "hardware_version": machine.hw_version,
            "capabilities": machine.configurations,
        }

    return {
        "config_entry": async_redact_data(entry.as_dict(), TO_REDACT),
        "device": async_redact_data(device, TO_REDACT) if device is not None else None,
        "last_update_success": coordinator.last_update_success,
        "data": coordinator.data,
    }
