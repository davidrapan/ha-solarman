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

DATA_SCHEMA = {
    vol.Required(CONF_NAME, default = DEFAULT_TABLE[CONF_NAME]): str,
    vol.Required(CONF_SERIAL, default = None): vol.All(vol.Coerce(int), vol.Range(min = 0, max = 4294967295))
}

OPTS_SCHEMA = {
    vol.Optional(CONF_HOST, default = DEFAULT_TABLE[CONF_HOST], description = {"suggested_value": DEFAULT_TABLE[CONF_HOST]}): str,
    vol.Optional(CONF_PORT, default = DEFAULT_TABLE[CONF_PORT], description = {"suggested_value": DEFAULT_TABLE[CONF_PORT]}): cv.port,
    vol.Optional(CONF_LOOKUP_FILE, default = DEFAULT_TABLE[CONF_LOOKUP_FILE], description = {"suggested_value": DEFAULT_TABLE[CONF_LOOKUP_FILE]}): str,
    vol.Required(CONF_ADDITIONAL_OPTIONS): section(
        vol.Schema(
            {
                vol.Optional(CONF_MPPT, default = DEFAULT_TABLE[CONF_MPPT], description = {"suggested_value": DEFAULT_TABLE[CONF_MPPT]}): vol.All(vol.Coerce(int), vol.Range(min = 1, max = 12)),
                vol.Optional(CONF_PHASE, default = DEFAULT_TABLE[CONF_PHASE], description = {"suggested_value": DEFAULT_TABLE[CONF_PHASE]}): vol.All(vol.Coerce(int), vol.Range(min = 1, max = 3)),
                vol.Optional(CONF_BATTERY_NOMINAL_VOLTAGE, default = DEFAULT_TABLE[CONF_BATTERY_NOMINAL_VOLTAGE], description = {"suggested_value": DEFAULT_TABLE[CONF_BATTERY_NOMINAL_VOLTAGE]}): cv.positive_int,
                vol.Optional(CONF_BATTERY_LIFE_CYCLE_RATING, default = DEFAULT_TABLE[CONF_BATTERY_LIFE_CYCLE_RATING], description = {"suggested_value": DEFAULT_TABLE[CONF_BATTERY_LIFE_CYCLE_RATING]}): cv.positive_int,
                vol.Optional(CONF_MB_SLAVE_ID, default = DEFAULT_TABLE[CONF_MB_SLAVE_ID], description = {"suggested_value": DEFAULT_TABLE[CONF_MB_SLAVE_ID]}): cv.positive_int
            }
        ),
        {"collapsed": True}
    )
}

async def async_update_listener(hass: HomeAssistant, config_entry: ConfigEntry) -> None:
    _LOGGER.debug(f"async_update_listener: entry: {config_entry.as_dict()}")
    #hass.data[DOMAIN][entry.entry_id].config(entry)
    #entry.title = entry.options[CONF_NAME]
    await hass.config_entries.async_reload(config_entry.entry_id)

async def data_schema(hass: HomeAssistant, data_schema: dict[str, Any]) -> vol.Schema:
    lookup_files = [DEFAULT_TABLE[CONF_LOOKUP_FILE]] + await async_listdir(hass.config.path(LOOKUP_DIRECTORY_PATH)) + await async_listdir(hass.config.path(LOOKUP_CUSTOM_DIRECTORY_PATH), "custom/")
    _LOGGER.debug(f"step_user_data_schema: {LOOKUP_DIRECTORY_PATH}: {lookup_files}")
    data_schema[CONF_LOOKUP_FILE] = vol.In(lookup_files)
    _LOGGER.debug(f"step_user_data_schema: data_schema: {data_schema}")
    return vol.Schema(data_schema)

def validate_connection(user_input: dict[str, Any], errors: dict) -> dict[str, Any]:
    _LOGGER.debug(f"validate_connection: {user_input}")

    try:
        if host := user_input.get(CONF_HOST, IP_ANY):
            getaddrinfo(host, user_input.get(CONF_PORT, DEFAULT_TABLE[CONF_PORT]), family = 0, type = 0, proto = 0, flags = 0)
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

def remove_defaults(user_input: dict[str, Any]):
    for k in list(user_input.keys()):
        if k == CONF_ADDITIONAL_OPTIONS:
            for l in list(user_input[k].keys()):
                if user_input[k][l] == DEFAULT_TABLE.get(l):
                    del user_input[k][l]
            if not user_input[k]:
                del user_input[k]
        elif user_input[k] == DEFAULT_TABLE.get(k):
            del user_input[k]
    return user_input

class ConfigFlowHandler(ConfigFlow, domain = DOMAIN):
    MINOR_VERSION = 3
    VERSION = 1

    async def _async_set_and_abort_if_unique_id_configured(self, suffix: str):
        await self.async_set_unique_id(f"solarman_{suffix}") # self._abort_if_unique_id_configured(updates={CONF_HOST: url.host})
        self._abort_if_unique_id_configured()

    async def async_step_dhcp(self, discovery_info: DhcpServiceInfo) -> ConfigFlowResult:
        _LOGGER.debug(f"ConfigFlowHandler.async_step_dhcp: {discovery_info}")
        #await self.async_set_unique_id(format_mac(discovery_info.macaddress))
        discovery_input = { CONF_NAME: DEFAULT_TABLE[CONF_NAME], CONF_HOST: discovery_info.ip, CONF_PORT: DEFAULT_TABLE[CONF_PORT] }
        self._async_abort_entries_match(discovery_input)
        return await self.async_step_user(user_input = discovery_input)

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        _LOGGER.debug(f"ConfigFlowHandler.async_step_user: {user_input}")
        if user_input is None:
            name = None
            serial = None
            ip = None
            if (discovered := await InverterDiscovery(self.hass).discover()):
                for s in discovered:
                    try:
                        self._async_abort_entries_match({ CONF_SERIAL: s })
                        ip = discovered[(serial := s)]["ip"]
                        break
                    except:
                        continue
                for i in range(0, 1000):
                    try:
                        self._async_abort_entries_match({ CONF_NAME: (name := ' '.join(filter(None, (DEFAULT_TABLE[CONF_NAME], None if not i else str(i if i != 1 else 2))))) })
                        break
                    except:
                        continue
            return self.async_show_form(step_id = "user", data_schema = self.add_suggested_values_to_schema(await data_schema(self.hass, DATA_SCHEMA | OPTS_SCHEMA), {CONF_NAME: name, CONF_SERIAL: serial, CONF_HOST: ip}))

        errors = {}

        if validate_connection(user_input, errors):
            await self._async_set_and_abort_if_unique_id_configured(user_input[CONF_SERIAL])
            return self.async_create_entry(title = user_input[CONF_NAME], data = filter_by_keys(user_input, DATA_SCHEMA), options = remove_defaults(filter_by_keys(user_input, OPTS_SCHEMA)))

        _LOGGER.debug(f"ConfigFlowHandler.async_step_user: connection validation failed: {user_input}")

        return self.async_show_form(step_id = "user", data_schema = self.add_suggested_values_to_schema(await data_schema(self.hass, DATA_SCHEMA | OPTS_SCHEMA), user_input), errors = errors)

    @staticmethod
    @callback
    def async_get_options_flow(entry: ConfigEntry) -> OptionsFlowHandler:
        _LOGGER.debug(f"ConfigFlowHandler.async_get_options_flow: {entry}")
        return OptionsFlowHandler(entry)

class OptionsFlowHandler(OptionsFlow):
    def __init__(self, entry: ConfigEntry) -> None:
        _LOGGER.debug(f"OptionsFlowHandler.__init__: {entry}")
        self.entry = entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        _LOGGER.debug(f"OptionsFlowHandler.async_step_init: user_input: {user_input}, current: {self.entry.options}")
        if user_input is None:
            return self.async_show_form(step_id = "init", data_schema = self.add_suggested_values_to_schema(await data_schema(self.hass, OPTS_SCHEMA), self.entry.options))

        errors = {}

        if validate_connection(user_input, errors):
            return self.async_create_entry(title = self.entry.data[CONF_NAME], data = remove_defaults(user_input))

        _LOGGER.debug(f"OptionsFlowHandler.async_step_init: connection validation failed: {user_input}")

        return self.async_show_form(step_id = "init", data_schema = self.add_suggested_values_to_schema(await data_schema(self.hass, OPTS_SCHEMA), user_input), errors = errors)
