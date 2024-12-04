from __future__ import annotations

import logging
import voluptuous as vol

from typing import Any
from socket import getaddrinfo, herror, gaierror, timeout

from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.helpers import config_validation as cv
from homeassistant.components.dhcp import DhcpServiceInfo
from homeassistant.data_entry_flow import section

from .const import *
from .common import *
from .discovery import InverterDiscovery

_LOGGER = logging.getLogger(__name__)

DATA_SCHEMA = { vol.Required(CONF_NAME, default = DEFAULT_NAME): str, vol.Required(CONF_SERIAL, default = None): cv.positive_int }

OPTS_SCHEMA = {
    vol.Required(CONF_HOST): str,
    vol.Optional(CONF_PORT, default = DEFAULT_INVERTER_PORT): cv.port,
    vol.Optional(CONF_LOOKUP_FILE, default = DEFAULT_LOOKUP_FILE): str,
    vol.Required(CONF_ADDITIONAL_OPTIONS): section(
        vol.Schema(
            {
                vol.Optional(CONF_MPPT, default = DEFAULT_MPPT): vol.All(vol.Coerce(int), vol.Range(min=1, max=12)),
                vol.Optional(CONF_PHASE, default = DEFAULT_PHASE): vol.All(vol.Coerce(int), vol.Range(min=1, max=3)),
                vol.Optional(CONF_BATTERY_NOMINAL_VOLTAGE, default = DEFAULT_BATTERY_NOMINAL_VOLTAGE): cv.positive_int,
                vol.Optional(CONF_BATTERY_LIFE_CYCLE_RATING, default = DEFAULT_BATTERY_LIFE_CYCLE_RATING): cv.positive_int,
                vol.Optional(CONF_MB_SLAVE_ID, default = DEFAULT_MB_SLAVE_ID): cv.positive_int
            }
        ),
        {"collapsed": True}
    )
}

async def async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    _LOGGER.debug(f"async_update_listener: entry: {entry.as_dict()}")
    #hass.data[DOMAIN][entry.entry_id].config(entry)
    #entry.title = entry.options[CONF_NAME]
    await hass.config_entries.async_reload(entry.entry_id)

async def data_schema(hass: HomeAssistant, data_schema: dict[str, Any]) -> vol.Schema:
    lookup_files = [DEFAULT_LOOKUP_FILE] + await async_listdir(hass.config.path(LOOKUP_DIRECTORY_PATH)) + await async_listdir(hass.config.path(LOOKUP_CUSTOM_DIRECTORY_PATH), "custom/")
    _LOGGER.debug(f"step_user_data_schema: {LOOKUP_DIRECTORY_PATH}: {lookup_files}")
    data_schema[CONF_LOOKUP_FILE] = vol.In(lookup_files)
    _LOGGER.debug(f"step_user_data_schema: data_schema: {data_schema}")
    return vol.Schema(data_schema)

def validate_connection(user_input: dict[str, Any], errors: dict) -> dict[str, Any]:
    """
    Validate the user input allows us to connect.

    Data has the keys from data_schema with values provided by the user.
    """
    _LOGGER.debug(f"validate_connection: {user_input}")

    try:
        getaddrinfo(user_input[CONF_HOST], user_input[CONF_PORT], family = 0, type = 0, proto = 0, flags = 0)
    except herror:
        errors["base"] = "invalid_host"
    except (gaierror, timeout):
        errors["base"] = "cannot_connect"
    except Exception as e:
        _LOGGER.exception(f"validate_connection: {format_exception(e)}")
        errors["base"] = "unknown"
    else:
        _LOGGER.debug(f"validate_connection: validation passed: {user_input}")
        return True

    return False

class ConfigFlowHandler(ConfigFlow, domain = DOMAIN):
    """Handle a solarman stick logger config flow."""
    MINOR_VERSION = 2
    VERSION = 1

    async def _async_try_and_abort_if_unique_id(self, unique_id):
        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured()

    async def async_step_dhcp(self, discovery_info: DhcpServiceInfo) -> ConfigFlowResult:
        """Handle a flow initiated by the DHCP client."""
        _LOGGER.debug(f"ConfigFlowHandler.async_step_dhcp: {discovery_info}")
        #await self.async_set_unique_id(format_mac(discovery_info.macaddress))
        discovery_input = { CONF_NAME: DEFAULT_NAME, CONF_HOST: discovery_info.ip, CONF_PORT: DEFAULT_INVERTER_PORT }
        self._async_abort_entries_match(discovery_input)
        return await self.async_step_user(user_input = discovery_input)

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle the initial step."""
        _LOGGER.debug(f"ConfigFlowHandler.async_step_user: {user_input}")
        if user_input is None:
            ip = None
            serial = None
            if (discovered := await InverterDiscovery(self.hass).discover()):
                for s in discovered:
                    try:
                        await self.async_set_unique_id(f"solarman_{s}")
                        self._abort_if_unique_id_configured()
                        ip = discovered[(serial := s)]["ip"]
                        break
                    except:
                        continue
            return self.async_show_form(step_id = "user", data_schema = self.add_suggested_values_to_schema(await data_schema(self.hass, DATA_SCHEMA | OPTS_SCHEMA), {CONF_HOST: ip, CONF_SERIAL: serial}))

        errors = {}

        if validate_connection(user_input, errors):
            await self.async_set_unique_id(f"solarman_{user_input[CONF_SERIAL]}")
            self._abort_if_unique_id_configured() #self._abort_if_unique_id_configured(updates={CONF_HOST: url.host})
            user_input_items = user_input.items()
            return self.async_create_entry(title = user_input[CONF_NAME], data = {k: v for k, v in user_input_items if k in DATA_SCHEMA}, options = {k: v for k, v in user_input_items if k in OPTS_SCHEMA})

        _LOGGER.debug(f"ConfigFlowHandler.async_step_user: validation failed: {user_input}")

        return self.async_show_form(step_id = "user", data_schema = self.add_suggested_values_to_schema(await data_schema(self.hass, DATA_SCHEMA | OPTS_SCHEMA), user_input), errors = errors)

    @staticmethod
    @callback
    def async_get_options_flow(entry: ConfigEntry) -> OptionsFlowHandler:
        """Get the options flow for this handler."""
        _LOGGER.debug(f"ConfigFlowHandler.async_get_options_flow: {entry}")
        return OptionsFlowHandler(entry)

class OptionsFlowHandler(OptionsFlow):
    """Handle a solarman stick logger options flow."""

    def __init__(self, entry: ConfigEntry) -> None:
        """Initialize options flow."""
        _LOGGER.debug(f"OptionsFlowHandler.__init__: {entry}")
        self.entry = entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle options flow."""
        _LOGGER.debug(f"OptionsFlowHandler.async_step_init: user_input: {user_input}, current: {self.entry.options}")
        if user_input is None:
            return self.async_show_form(step_id = "init", data_schema = self.add_suggested_values_to_schema(await data_schema(self.hass, OPTS_SCHEMA), self.entry.options))

        errors = {}

        if validate_connection(user_input, errors):
            return self.async_create_entry(title = self.entry.data[CONF_NAME], data = user_input)

        return self.async_show_form(step_id = "init", data_schema = self.add_suggested_values_to_schema(await data_schema(self.hass, OPTS_SCHEMA), user_input), errors = errors)
