from __future__ import annotations

import logging
import voluptuous as vol

from typing import Any
from socket import getaddrinfo, herror, gaierror, timeout

from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.data_entry_flow import section, AbortFlow
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.helpers.selector import selector
from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo

from .const import *
from .common import *
from .discovery import Discovery

_LOGGER = logging.getLogger(__name__)

DATA_SCHEMA = {
    vol.Required(CONF_NAME, default = DEFAULT_[CONF_NAME]): str
}

OPTS_SCHEMA = {
    vol.Required(CONF_HOST, default = DEFAULT_[CONF_HOST], description = {SUGGESTED_VALUE: DEFAULT_[CONF_HOST]}): str,
    vol.Optional(CONF_PORT, default = DEFAULT_[CONF_PORT], description = {SUGGESTED_VALUE: DEFAULT_[CONF_PORT]}): cv.port,
    vol.Optional(CONF_TRANSPORT, default = DEFAULT_[CONF_TRANSPORT], description = {SUGGESTED_VALUE: DEFAULT_[CONF_TRANSPORT]}): selector({
        "select": {
            "mode": "dropdown",
            "options": ["tcp", "modbus_tcp"],
            "translation_key": "transport"
        }
    }),
    vol.Optional(CONF_LOOKUP_FILE, default = DEFAULT_[CONF_LOOKUP_FILE], description = {SUGGESTED_VALUE: DEFAULT_[CONF_LOOKUP_FILE]}): str,
    vol.Required(CONF_ADDITIONAL_OPTIONS): section(
        vol.Schema(
            {
                vol.Optional(CONF_MOD, default = DEFAULT_[CONF_MOD], description = {SUGGESTED_VALUE: DEFAULT_[CONF_MOD]}): bool,
                vol.Optional(CONF_MPPT, default = DEFAULT_[CONF_MPPT], description = {SUGGESTED_VALUE: DEFAULT_[CONF_MPPT]}): vol.All(vol.Coerce(int), vol.Range(min = 1, max = 12)),
                vol.Optional(CONF_PHASE, default = DEFAULT_[CONF_PHASE], description = {SUGGESTED_VALUE: DEFAULT_[CONF_PHASE]}): vol.All(vol.Coerce(int), vol.Range(min = 1, max = 3)),
                vol.Optional(CONF_PACK, default = DEFAULT_[CONF_PACK], description = {SUGGESTED_VALUE: DEFAULT_[CONF_PACK]}): vol.All(vol.Coerce(int), vol.Range(min = -1, max = 12)),
                vol.Optional(CONF_BATTERY_NOMINAL_VOLTAGE, default = DEFAULT_[CONF_BATTERY_NOMINAL_VOLTAGE], description = {SUGGESTED_VALUE: DEFAULT_[CONF_BATTERY_NOMINAL_VOLTAGE]}): cv.positive_int,
                vol.Optional(CONF_BATTERY_LIFE_CYCLE_RATING, default = DEFAULT_[CONF_BATTERY_LIFE_CYCLE_RATING], description = {SUGGESTED_VALUE: DEFAULT_[CONF_BATTERY_LIFE_CYCLE_RATING]}): cv.positive_int,
                vol.Optional(CONF_MB_SLAVE_ID, default = DEFAULT_[CONF_MB_SLAVE_ID], description = {SUGGESTED_VALUE: DEFAULT_[CONF_MB_SLAVE_ID]}): cv.positive_int
            }
        ),
        {"collapsed": True}
    )
}

async def data_schema(hass: HomeAssistant, data_schema: dict[str, Any]) -> vol.Schema:
    lookup_files = [DEFAULT_[CONF_LOOKUP_FILE]] + await async_listdir(hass.config.path(LOOKUP_DIRECTORY_PATH)) + await async_listdir(hass.config.path(LOOKUP_CUSTOM_DIRECTORY_PATH), "custom/")
    _LOGGER.debug(f"step_user_data_schema: {LOOKUP_DIRECTORY_PATH}: {lookup_files}")
    data_schema[CONF_LOOKUP_FILE] = vol.In(lookup_files)
    _LOGGER.debug(f"step_user_data_schema: data_schema: {data_schema}")
    return vol.Schema(data_schema)

def validate_connection(user_input: dict[str, Any], errors: dict) -> dict[str, Any]:
    _LOGGER.debug(f"validate_connection: {user_input}")

    try:
        if host := user_input.get(CONF_HOST, IP_ANY):
            getaddrinfo(host, user_input.get(CONF_PORT, DEFAULT_[CONF_PORT]), family = 0, type = 0, proto = 0, flags = 0)
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
                if user_input[k][l] == DEFAULT_.get(l):
                    del user_input[k][l]
            if not user_input[k]:
                del user_input[k]
        elif user_input[k] == DEFAULT_.get(k):
            del user_input[k]
    return user_input

class ConfigFlowHandler(ConfigFlow, domain = DOMAIN):
    MINOR_VERSION = 9
    VERSION = 1

    async def async_step_dhcp(self, discovery_info: DhcpServiceInfo) -> ConfigFlowResult:
        _LOGGER.debug(f"ConfigFlowHandler.async_step_dhcp: {discovery_info}")
        if (device := dr.async_get(self.hass).async_get_device(connections = {(dr.CONNECTION_NETWORK_MAC, dr.format_mac(discovery_info.macaddress))})) is not None:
            for entry in self._async_current_entries():
                if entry.entry_id in device.config_entries and entry.options.get(CONF_HOST) != discovery_info.ip:
                    self.hass.config_entries.async_update_entry(entry, options = entry.options | {CONF_HOST: discovery_info.ip})
                    self.hass.async_create_task(self.hass.config_entries.async_reload(entry.entry_id))
                    return self.async_abort(reason = "already_configured")
        try:
            self._async_abort_entries_match({ CONF_HOST: discovery_info.ip })
        except:
            return self.async_abort(reason = "already_configured")
        await self._async_handle_discovery_without_unique_id()
        return await self.async_step_user()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        _LOGGER.debug(f"ConfigFlowHandler.async_step_user: {user_input}")
        if user_input is None:
            name = None
            ip = None
            if (discovered := await Discovery(self.hass).discover()):
                for s, v in discovered.items():
                    try:
                        self._async_abort_entries_match({ CONF_HOST: v["ip"] })
                        ip = v["ip"]
                        break
                    except:
                        continue
                for i in range(0, 1000):
                    try:
                        for entry in self._async_current_entries(include_ignore = False):
                            if entry.title == (name := ' '.join(filter(None, (DEFAULT_[CONF_NAME], None if not i else str(i if i != 1 else 2))))):
                                raise AbortFlow("already_configured")
                        break
                    except:
                        continue
                else:
                    name = None
            return self.async_show_form(step_id = "user", data_schema = self.add_suggested_values_to_schema(await data_schema(self.hass, DATA_SCHEMA | OPTS_SCHEMA), {CONF_NAME: name, CONF_HOST: ip}))

        errors = {}

        if validate_connection(user_input, errors):
            await self.async_set_unique_id(None)
            self._abort_if_unique_id_configured() #self._abort_if_unique_id_configured(updates={CONF_HOST: url.host})
            return self.async_create_entry(title = user_input[CONF_NAME], data = {}, options = remove_defaults(filter_by_keys(user_input, OPTS_SCHEMA)))

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
            return self.async_create_entry(data = remove_defaults(user_input))

        _LOGGER.debug(f"OptionsFlowHandler.async_step_init: connection validation failed: {user_input}")

        return self.async_show_form(step_id = "init", data_schema = self.add_suggested_values_to_schema(await data_schema(self.hass, OPTS_SCHEMA), user_input), errors = errors)
