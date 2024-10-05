from __future__ import annotations

import logging
import voluptuous as vol

from voluptuous.schema_builder import Schema
from socket import getaddrinfo, herror, gaierror, timeout
from typing import Any

from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.helpers.device_registry import format_mac
from homeassistant.helpers import config_validation as cv
from homeassistant.components.dhcp import DhcpServiceInfo
from homeassistant.exceptions import HomeAssistantError

from .const import *
from .common import *
from .discovery import InverterDiscovery

_LOGGER = logging.getLogger(__name__)

async def async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    _LOGGER.debug(f"async_update_listener: entry: {entry.as_dict()}")
    #hass.data[DOMAIN][entry.entry_id].config(entry)
    #entry.title = entry.options[CONF_NAME]
    await hass.config_entries.async_reload(entry.entry_id)

def step_user_data_prefill(ip, serial):
    _LOGGER.debug(f"step_user_data_prefill: IP: {ip}, serial: {serial}")
    return { CONF_NAME: DEFAULT_NAME, CONF_INVERTER_HOST: ip, CONF_SERIAL: serial, CONF_INVERTER_PORT: DEFAULT_INVERTER_PORT, CONF_MB_SLAVE_ID: DEFAULT_MB_SLAVE_ID, CONF_LOOKUP_FILE: DEFAULT_LOOKUP_FILE, CONF_BATTERY_NOMINAL_VOLTAGE: DEFAULT_BATTERY_NOMINAL_VOLTAGE, CONF_BATTERY_LIFE_CYCLE_RATING: DEFAULT_BATTERY_LIFE_CYCLE_RATING }

async def step_user_data_schema(hass: HomeAssistant, data: dict[str, Any] = { CONF_NAME: DEFAULT_NAME, CONF_INVERTER_PORT: DEFAULT_INVERTER_PORT, CONF_MB_SLAVE_ID: DEFAULT_MB_SLAVE_ID, CONF_LOOKUP_FILE: DEFAULT_LOOKUP_FILE, CONF_BATTERY_NOMINAL_VOLTAGE: DEFAULT_BATTERY_NOMINAL_VOLTAGE, CONF_BATTERY_LIFE_CYCLE_RATING: DEFAULT_BATTERY_LIFE_CYCLE_RATING }) -> vol.Schema:
    lookup_files = await async_listdir(hass.config.path(LOOKUP_DIRECTORY_PATH)) + await async_listdir(hass.config.path(LOOKUP_CUSTOM_DIRECTORY_PATH), "custom/")
    _LOGGER.debug(f"step_user_data_schema: data: {data}, {LOOKUP_DIRECTORY_PATH}: {lookup_files}")
    #data_schema = vol.Schema({ vol.Required(CONF_NAME, default = data.get(CONF_NAME)): str }, extra = vol.PREVENT_EXTRA) if wname else vol.Schema({}, extra = vol.PREVENT_EXTRA)
    #data_schema = data_schema.extend(
    data_schema = vol.Schema(
        {
            #vol.Optional("Example of"): "some text to display in the config flow..."
            vol.Required(CONF_NAME, default = data.get(CONF_NAME)): str,
            vol.Required(CONF_SERIAL, default = data.get(CONF_SERIAL)): cv.positive_int,
            vol.Required(CONF_INVERTER_HOST, default = data.get(CONF_INVERTER_HOST)): str,
            vol.Optional(CONF_INVERTER_PORT, default = data.get(CONF_INVERTER_PORT)): cv.port,
            vol.Optional(CONF_MB_SLAVE_ID, default = data.get(CONF_MB_SLAVE_ID)): cv.positive_int,
            vol.Optional(CONF_LOOKUP_FILE, default = data.get(CONF_LOOKUP_FILE)): vol.In(lookup_files),
            vol.Optional(CONF_BATTERY_NOMINAL_VOLTAGE, default = data.get(CONF_BATTERY_NOMINAL_VOLTAGE)): cv.positive_int,
            vol.Optional(CONF_BATTERY_LIFE_CYCLE_RATING, default = data.get(CONF_BATTERY_LIFE_CYCLE_RATING)): cv.positive_int,
        },
        extra = vol.PREVENT_EXTRA
    )
    _LOGGER.debug(f"step_user_data_schema: data_schema: {data_schema}")
    return data_schema

async def step_init_data_schema(hass: HomeAssistant, data: dict[str, Any] = { CONF_NAME: DEFAULT_NAME, CONF_INVERTER_PORT: DEFAULT_INVERTER_PORT, CONF_MB_SLAVE_ID: DEFAULT_MB_SLAVE_ID, CONF_LOOKUP_FILE: DEFAULT_LOOKUP_FILE, CONF_BATTERY_NOMINAL_VOLTAGE: DEFAULT_BATTERY_NOMINAL_VOLTAGE, CONF_BATTERY_LIFE_CYCLE_RATING: DEFAULT_BATTERY_LIFE_CYCLE_RATING }) -> vol.Schema:
    lookup_files = await async_listdir(hass.config.path(LOOKUP_DIRECTORY_PATH)) + await async_listdir(hass.config.path(LOOKUP_CUSTOM_DIRECTORY_PATH), "custom/")
    _LOGGER.debug(f"step_init_data_schema: data: {data}, {LOOKUP_DIRECTORY_PATH}: {lookup_files}")
    data_schema = vol.Schema(
        {
            vol.Required(CONF_INVERTER_HOST, default = data.get(CONF_INVERTER_HOST)): str,
            vol.Optional(CONF_INVERTER_PORT, default = data.get(CONF_INVERTER_PORT)): cv.port,
            vol.Optional(CONF_MB_SLAVE_ID, default = data.get(CONF_MB_SLAVE_ID)): cv.positive_int,
            vol.Optional(CONF_LOOKUP_FILE, default = data.get(CONF_LOOKUP_FILE)): vol.In(lookup_files),
            vol.Optional(CONF_BATTERY_NOMINAL_VOLTAGE, default = data.get(CONF_BATTERY_NOMINAL_VOLTAGE)): cv.positive_int,
            vol.Optional(CONF_BATTERY_LIFE_CYCLE_RATING, default = data.get(CONF_BATTERY_LIFE_CYCLE_RATING)): cv.positive_int,
        },
        extra = vol.PREVENT_EXTRA
    )
    _LOGGER.debug(f"step_init_data_schema: data_schema: {data_schema}")
    return data_schema

async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """
    Validate the user input allows us to connect.

    Data has the keys from data_schema with values provided by the user.
    """
    _LOGGER.debug(f"validate_input: {data}")

    try:
        getaddrinfo(data[CONF_INVERTER_HOST], data[CONF_INVERTER_PORT], family = 0, type = 0, proto = 0, flags = 0)
    except herror:
        raise InvalidHost
    except gaierror:
        raise CannotConnect
    except timeout:
        raise CannotConnect

    return data

class ConfigFlowHandler(ConfigFlow, domain = DOMAIN):
    """Handle a solarman stick logger config flow."""
    VERSION = 1

    async def _async_try_and_abort_if_unique_id(self, unique_id):
        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured()

    async def async_step_dhcp(self, discovery_info: DhcpServiceInfo) -> ConfigFlowResult:
        """Handle a flow initiated by the DHCP client."""
        _LOGGER.debug(f"ConfigFlowHandler.async_step_dhcp: {discovery_info}")
        #await self.async_set_unique_id(format_mac(discovery_info.macaddress))
        discovery_input = { CONF_NAME: DEFAULT_NAME,
            CONF_INVERTER_HOST: discovery_info.ip,
            CONF_INVERTER_PORT: DEFAULT_INVERTER_PORT }
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
            return self.async_show_form(step_id = "user", data_schema = await step_user_data_schema(self.hass, step_user_data_prefill(ip, serial)))

        errors = {}

        try:
            await validate_input(self.hass, user_input)
        except InvalidHost:
            errors["base"] = "invalid_host"
        except CannotConnect:
            errors["base"] = "cannot_connect"
        except Exception:
            _LOGGER.exception("Unexpected exception")
            errors["base"] = "unknown"
        else:
            _LOGGER.debug(f"ConfigFlowHandler.async_step_user: validation passed: {user_input}")
            await self.async_set_unique_id(f"solarman_{user_input[CONF_SERIAL]}") #self._abort_if_unique_id_configured(updates={CONF_HOST: url.host})
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title = user_input[CONF_NAME], data = user_input, options = user_input)

        _LOGGER.debug(f"ConfigFlowHandler.async_step_user: validation failed: {user_input}")

        return self.async_show_form(step_id = "user", data_schema = await step_user_data_schema(self.hass, user_input), errors = errors)

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
            return self.async_show_form(step_id = "init", data_schema = await step_init_data_schema(self.hass, self.entry.options))

        errors = {}

        try:
            await validate_input(self.hass, user_input)
        except InvalidHost:
            errors["base"] = "invalid_host"
        except CannotConnect:
            errors["base"] = "cannot_connect"
        except Exception:
            _LOGGER.exception("Unexpected exception")
            errors["base"] = "unknown"
        else:
            _LOGGER.debug(f"OptionsFlowHandler.async_step_init: validation passed: {user_input}")
            return self.async_create_entry(title = self.entry.data[CONF_NAME], data = user_input)

        return self.async_show_form(step_id = "init", data_schema = await step_init_data_schema(self.hass, user_input), errors = errors)

class InvalidHost(HomeAssistantError):
    """Error to indicate there is invalid hostname or IP address."""

class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""