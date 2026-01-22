from __future__ import annotations

import voluptuous as vol

from typing import Any
from logging import getLogger
from dataclasses import asdict
from socket import getaddrinfo, herror, gaierror, timeout

from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import section, AbortFlow
from homeassistant.config_entries import DEFAULT_DISCOVERY_UNIQUE_ID, ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.helpers.selector import SelectSelector, SelectSelectorConfig
from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo
from homeassistant.helpers.typing import DiscoveryInfoType

from .const import *
from .common import *
from .discovery import discover

_LOGGER = getLogger(__name__)

CREATION_SCHEMA = {
    vol.Required(CONF_NAME, default = DEFAULT_[CONF_NAME]): str
}

CONFIGURATION_SCHEMA = {
    vol.Required(CONF_HOST, default = DEFAULT_[CONF_HOST], description = {SUGGESTED_VALUE: DEFAULT_[CONF_HOST]}): str,
    vol.Optional(CONF_PORT, default = DEFAULT_[CONF_PORT], description = {SUGGESTED_VALUE: DEFAULT_[CONF_PORT]}): cv.port,
    vol.Optional(CONF_TRANSPORT, default = DEFAULT_[CONF_TRANSPORT], description = {SUGGESTED_VALUE: DEFAULT_[CONF_TRANSPORT]}): SelectSelector(SelectSelectorConfig(options = ["tcp", "modbus_tcp", "modbus_rtu"], mode = "dropdown", translation_key = "transport")),
    vol.Optional(CONF_LOOKUP_FILE, default = DEFAULT_[CONF_LOOKUP_FILE], description = {SUGGESTED_VALUE: DEFAULT_[CONF_LOOKUP_FILE]}): str,
    vol.Required(CONF_ADDITIONAL_OPTIONS): section(
        vol.Schema({
            vol.Optional(CONF_MOD, default = DEFAULT_[CONF_MOD], description = {SUGGESTED_VALUE: DEFAULT_[CONF_MOD]}): vol.All(vol.Coerce(int), vol.Range(min = 0, max = 2)),
            vol.Optional(CONF_MPPT, default = DEFAULT_[CONF_MPPT], description = {SUGGESTED_VALUE: DEFAULT_[CONF_MPPT]}): vol.All(vol.Coerce(int), vol.Range(min = 1, max = 12)),
            vol.Optional(CONF_PHASE, default = DEFAULT_[CONF_PHASE], description = {SUGGESTED_VALUE: DEFAULT_[CONF_PHASE]}): vol.All(vol.Coerce(int), vol.Range(min = 1, max = 3)),
            vol.Optional(CONF_PACK, default = DEFAULT_[CONF_PACK], description = {SUGGESTED_VALUE: DEFAULT_[CONF_PACK]}): vol.All(vol.Coerce(int), vol.Range(min = -1, max = 20)),
            vol.Optional(CONF_BATTERY_NOMINAL_VOLTAGE, default = DEFAULT_[CONF_BATTERY_NOMINAL_VOLTAGE], description = {SUGGESTED_VALUE: DEFAULT_[CONF_BATTERY_NOMINAL_VOLTAGE]}): cv.positive_float,
            vol.Optional(CONF_BATTERY_LIFE_CYCLE_RATING, default = DEFAULT_[CONF_BATTERY_LIFE_CYCLE_RATING], description = {SUGGESTED_VALUE: DEFAULT_[CONF_BATTERY_LIFE_CYCLE_RATING]}): cv.positive_int,
            vol.Optional(CONF_MB_SLAVE_ID, default = DEFAULT_[CONF_MB_SLAVE_ID], description = {SUGGESTED_VALUE: DEFAULT_[CONF_MB_SLAVE_ID]}): cv.positive_int
        }),
        {"collapsed": True}
    )
}

async def data_schema(hass: HomeAssistant, data_schema: dict[str, Any]) -> vol.Schema:
    data_schema[CONF_LOOKUP_FILE] = vol.In([DEFAULT_[CONF_LOOKUP_FILE]] + await async_listdir(hass.config.path(LOOKUP_DIRECTORY_PATH)) + await async_listdir(hass.config.path(LOOKUP_CUSTOM_DIRECTORY_PATH), "custom/"))
    _LOGGER.debug(f"step_user_data_schema: data_schema: {data_schema}")
    return vol.Schema(data_schema)

def validate_connection(user_input: dict[str, Any]) -> dict[str, Any]:
    _LOGGER.debug(f"validate_connection: {user_input}")
    error = "unknown"
    try:
        if host := user_input.get(CONF_HOST, IP_ANY):
            getaddrinfo(host, user_input.get(CONF_PORT, DEFAULT_[CONF_PORT]), family = 0, type = 0, proto = 0, flags = 0)
    except herror:
        error = "invalid_host"
    except timeout:
        error = "timeout_connect"
    except gaierror:
        error = "cannot_connect"
    except Exception as e:
        _LOGGER.exception(f"validate_connection: {strepr(e)}")
    else:
        _LOGGER.debug(f"validate_connection: validation passed: {user_input}")
        return None
    _LOGGER.debug(f"validate_connection: validation failed: {user_input}")
    return {"base": error}

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
    MINOR_VERSION = 0
    VERSION = 2

    async def _handle_discovery(self, **discovery_info: str | int) -> ConfigFlowResult:
        _LOGGER.debug(f"Solarman found from {"integration" if "serial" in discovery_info else "dhcp"} discovery on {discovery_info["ip"]}")
        connections = {(dr.CONNECTION_NETWORK_MAC, dr.format_mac(discovery_info["mac"]))}
        if device := dr.async_get(self.hass).async_get_device(connections = connections):
            for entry in self._async_current_entries():
                if entry.entry_id == device.primary_config_entry:
                    if str(getipaddress(entry.options.get(CONF_HOST))) != discovery_info["ip"] and discovery_info["ip"] != IP_ANY:
                        self.hass.config_entries.async_update_entry(entry, options = entry.options | {CONF_HOST: discovery_info["ip"]})
                    return self.async_abort(reason = "already_configured_device")
        for entry in self._async_current_entries():
            if str(getipaddress(entry.options.get(CONF_HOST))) == discovery_info["ip"]:
                if device := dr.async_get(self.hass).async_get_device(identifiers = {(DOMAIN, entry.entry_id)}):
                    dr.async_get(self.hass).async_update_device(device.id, new_connections = connections)
                return self.async_abort(reason = "already_configured_device")
        await self.async_set_unique_id(DEFAULT_DISCOVERY_UNIQUE_ID)
        self._abort_if_unique_id_configured()
        if self._async_in_progress(include_uninitialized = True):
            raise AbortFlow("already_in_progress")
        input = {CONF_HOST: discovery_info["ip"]} | ({"hostname": hostname} if (hostname := discovery_info.get("hostname")) and (hostname := hostname.capitalize()) else {})
        self.context.update({"title_placeholders": {CONF_NAME: hostname or discovery_info["ip"]}, "configuration_url": build_configuration_url(discovery_info["ip"])})
        return await self.async_step_user(input)

    async def async_step_integration_discovery(self, discovery_info: DiscoveryInfoType) -> ConfigFlowResult:
        return await self._handle_discovery(**discovery_info)

    async def async_step_dhcp(self, discovery_info: DhcpServiceInfo) -> ConfigFlowResult:
        return await self._handle_discovery(**asdict(discovery_info), mac = discovery_info.macaddress)

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        _LOGGER.debug(f"ConfigFlowHandler.async_step_user: {user_input}")
        if user_input is None or not user_input.get(CONF_NAME):
            name = None if not user_input else user_input.get("hostname")
            for i in range(0, 1000):
                try:
                    for entry in self._async_current_entries(include_ignore = False):
                        if entry.title == (name := ' '.join(filter(None, (DEFAULT_[CONF_NAME], None if not i else str(i if i != 1 else 2))))):
                            raise AbortFlow("already_configured_device")
                    break
                except:
                    continue
            else:
                name = None
            if not (ip := None if not user_input else user_input.get(CONF_HOST)):
                async for v in await discover(self.hass):
                    try:
                        self._async_abort_entries_match({CONF_HOST: (ip := v["ip"])})
                        break
                    except:
                        continue
                else:
                    ip = None
            return self.async_show_form(step_id = "user", data_schema = self.add_suggested_values_to_schema(await data_schema(self.hass, CREATION_SCHEMA | CONFIGURATION_SCHEMA), {CONF_NAME: name, CONF_HOST: ip}))
        if errors := validate_connection(user_input):
            return self.async_show_form(step_id = "user", data_schema = self.add_suggested_values_to_schema(await data_schema(self.hass, CREATION_SCHEMA | CONFIGURATION_SCHEMA), user_input), errors = errors)
        return self.async_create_entry(title = user_input[CONF_NAME], data = {}, options = remove_defaults(filter_by_keys(user_input, CONFIGURATION_SCHEMA)))

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
            return self.async_show_form(step_id = "init", data_schema = self.add_suggested_values_to_schema(await data_schema(self.hass, CONFIGURATION_SCHEMA), self.entry.options))
        if errors := validate_connection(user_input):
            return self.async_show_form(step_id = "init", data_schema = self.add_suggested_values_to_schema(await data_schema(self.hass, CONFIGURATION_SCHEMA), user_input), errors = errors)
        return self.async_create_entry(data = remove_defaults(user_input))
