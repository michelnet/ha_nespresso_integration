"""Config flow for the Nespresso integration."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass
from typing import Any, override

import voluptuous as vol
from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_ble_device_from_address,
    async_discovered_service_info,
)
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_ADDRESS, CONF_TOKEN
from homeassistant.helpers import config_validation as cv

from .auth import is_valid_auth_token, normalize_auth_token
from .const import DOMAIN, NESPRESSO_SERVICE_UUID
from .machines import supported
from .nespresso import (
    NespressoAuthenticationError,
    NespressoClient,
    NespressoConnectionError,
    NespressoError,
)

_LOGGER = logging.getLogger(__name__)

# Config-flow schemas are serialized and sent to the frontend. Keep this
# validator limited to primitives supported by voluptuous-serialize, and do
# format validation in the step handler below.
AUTH_TOKEN_FIELD = vol.All(cv.string, vol.Strip)


def _auth_code_from_input(
    user_input: Mapping[str, Any], *, required: bool = False
) -> tuple[str | None, dict[str, str]]:
    """Normalize and validate an authentication token from a form."""

    auth_code = normalize_auth_token(user_input.get(CONF_TOKEN))
    if auth_code is None:
        if required:
            return None, {CONF_TOKEN: "invalid_token"}
        return None, {}
    if not is_valid_auth_token(auth_code):
        return None, {CONF_TOKEN: "invalid_token"}
    return auth_code, {}


@dataclass(frozen=True, slots=True)
class Discovery:
    """A discovered, supported Nespresso device."""

    title: str
    service_info: BluetoothServiceInfoBleak


class NespressoConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for a Nespresso Bluetooth machine."""

    VERSION = 2

    def __init__(self) -> None:
        """Initialize per-flow discovery state."""
        self._discovery_info: BluetoothServiceInfoBleak | None = None
        self._discovered_devices: dict[str, Discovery] = {}
        self._pending_auth_codes: dict[str, str] = {}
        self._reauth_address: str | None = None

    @staticmethod
    def _is_candidate(discovery_info: BluetoothServiceInfoBleak) -> bool:
        """Return whether an advertisement can be a supported machine."""
        return bool(
            supported(discovery_info.name)
            or NESPRESSO_SERVICE_UUID
            in (service_uuid.lower() for service_uuid in discovery_info.service_uuids)
        )

    async def _async_validate_device(self, address: str, auth_code: str | None) -> tuple[str, str]:
        """Connect, authenticate, and return the machine title and auth code."""
        ble_device = async_ble_device_from_address(self.hass, address, connectable=True)
        if ble_device is None:
            raise NespressoConnectionError(f"Bluetooth device {address} is not currently available")

        supplied_auth_code = auth_code is not None
        client = NespressoClient(
            auth_code=auth_code or self._pending_auth_codes.get(address),
            mac=address,
        )
        try:
            if not await client.connect(ble_device):
                raise NespressoConnectionError(f"Unable to connect to Bluetooth device {address}")
            machine = await client.load_model()
            if machine is None or not supported(machine.name):
                raise NespressoError("Unsupported Nespresso machine")
            if client.auth_code is None:
                raise NespressoAuthenticationError(
                    "The machine did not provide a usable authentication key"
                )
            return machine.name, client.auth_code
        finally:
            # Keep a newly generated key for a retry if onboarding succeeded but
            # a later verification read failed. Losing that key would leave the
            # machine paired with a credential the flow no longer knows.
            if not supplied_auth_code and client.auth_code is not None:
                self._pending_auth_codes[address] = client.auth_code
            # Cleanup must never hide the actual validation or authentication
            # error shown by the config flow.
            with suppress(Exception):
                await client.disconnect()

    async def _async_try_validate(
        self, address: str, auth_code: str | None
    ) -> tuple[tuple[str, str] | None, dict[str, str]]:
        """Validate flow input and translate expected failures to form errors."""
        try:
            return await self._async_validate_device(address, auth_code), {}
        except NespressoAuthenticationError as err:
            _LOGGER.debug("Nespresso authentication failed: %s", err)
            return None, {"base": "invalid_auth" if auth_code is not None else "cannot_pair"}
        except NespressoConnectionError as err:
            _LOGGER.debug("Unable to connect to Nespresso device: %s", err)
            return None, {"base": "cannot_connect"}
        except NespressoError as err:
            _LOGGER.debug("Unable to configure Nespresso device: %s", err)
            return None, {"base": "cannot_pair"}
        except Exception:
            _LOGGER.exception("Unexpected error while configuring Nespresso device")
            return None, {"base": "unknown"}

    @staticmethod
    def _token_schema(required: bool = False) -> vol.Schema:
        """Return the authentication-key form schema."""
        marker: vol.Marker
        if required:
            marker = vol.Required(CONF_TOKEN)
        else:
            marker = vol.Optional(CONF_TOKEN)
        return vol.Schema({marker: AUTH_TOKEN_FIELD})

    @override
    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Handle a Bluetooth discovery without connecting prematurely."""
        if not self._is_candidate(discovery_info):
            return self.async_abort(reason="not_supported")

        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()

        self._discovery_info = discovery_info
        self.context["title_placeholders"] = {"name": discovery_info.name or discovery_info.address}
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm discovery, then pair and create the config entry."""
        assert self._discovery_info is not None
        errors: dict[str, str] = {}

        if user_input is not None:
            auth_code, errors = _auth_code_from_input(user_input)
            if not errors:
                result, errors = await self._async_try_validate(
                    self._discovery_info.address, auth_code
                )
                if result is not None:
                    title, auth_code = result
                    return self.async_create_entry(
                        title=title,
                        data={
                            CONF_ADDRESS: self._discovery_info.address,
                            CONF_TOKEN: auth_code,
                        },
                    )

        return self.async_show_form(
            step_id="bluetooth_confirm",
            data_schema=self._token_schema(),
            description_placeholders=self.context["title_placeholders"],
            errors=errors,
        )

    @override
    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Let the user select a discovered machine."""
        errors: dict[str, str] = {}
        if user_input is not None:
            auth_code, errors = _auth_code_from_input(user_input)
            if not errors:
                address: str = user_input[CONF_ADDRESS]
                discovery = self._discovered_devices[address]
                self._discovery_info = discovery.service_info

                await self.async_set_unique_id(address, raise_on_progress=False)
                self._abort_if_unique_id_configured()
                self.context["title_placeholders"] = {"name": discovery.title}

                result, errors = await self._async_try_validate(address, auth_code)
                if result is not None:
                    title, auth_code = result
                    return self.async_create_entry(
                        title=title,
                        data={CONF_ADDRESS: address, CONF_TOKEN: auth_code},
                    )

        if not self._discovered_devices:
            await bluetooth.async_request_active_scan(self.hass)
            current_addresses = self._async_current_ids(include_ignore=False)
            for service_info in async_discovered_service_info(self.hass, True):
                address = service_info.address
                if (
                    address in current_addresses
                    or address in self._discovered_devices
                    or not self._is_candidate(service_info)
                ):
                    continue
                self._discovered_devices[address] = Discovery(
                    title=service_info.name or address,
                    service_info=service_info,
                )

        if not self._discovered_devices:
            return self.async_abort(reason="no_devices_found")

        titles = {
            address: discovery.title for address, discovery in self._discovered_devices.items()
        }
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ADDRESS): vol.In(titles),
                    vol.Optional(CONF_TOKEN): AUTH_TOKEN_FIELD,
                }
            ),
            errors=errors,
        )

    @override
    async def async_step_reauth(self, _entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """Start reauthentication after the stored key was rejected."""
        entry = self._get_reauth_entry()
        self._reauth_address = entry.data[CONF_ADDRESS]
        self.context["title_placeholders"] = {"name": entry.title}
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Validate and save a replacement authentication key."""
        assert self._reauth_address is not None
        errors: dict[str, str] = {}

        if user_input is not None:
            auth_code, errors = _auth_code_from_input(user_input, required=True)
            if not errors:
                result, errors = await self._async_try_validate(self._reauth_address, auth_code)
                if result is not None:
                    title, auth_code = result
                    return self.async_update_reload_and_abort(
                        self._get_reauth_entry(),
                        title=title,
                        data_updates={CONF_TOKEN: auth_code},
                    )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=self._token_schema(required=True),
            description_placeholders=self.context["title_placeholders"],
            errors=errors,
        )
