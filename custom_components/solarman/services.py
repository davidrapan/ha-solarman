from __future__ import annotations

import voluptuous as vol

from logging import getLogger

from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.device_registry import async_get
from homeassistant.exceptions import ServiceValidationError
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse

from .const import *
from .coordinator import Coordinator
from .pysolarman.umodbus.functions import FUNCTION_CODE

_LOGGER = getLogger(__name__)

HEADER_SCHEMA = {
    vol.Required(SERVICES_PARAM_DEVICE): vol.All(vol.Coerce(str)),
    vol.Required(SERVICES_PARAM_ADDRESS): vol.All(vol.Coerce(int), vol.Range(min = 0, max = 65535))
}

DEPRECATION_HEADER_SCHEMA = {
    vol.Required(SERVICES_PARAM_DEVICE): vol.All(vol.Coerce(str)),
    vol.Required(SERVICES_PARAM_REGISTER): vol.All(vol.Coerce(int), vol.Range(min = 0, max = 65535))
}

COUNT_SCHEMA = {vol.Required(SERVICES_PARAM_COUNT): vol.All(vol.Coerce(int), vol.Range(min = 0, max = 125))}
VALUE_SCHEMA = {vol.Required(SERVICES_PARAM_VALUE): vol.All(vol.Coerce(int), vol.Range(min = 0, max = 65535))}
VALUES_SCHEMA = {vol.Required(SERVICES_PARAM_VALUES): vol.All(cv.ensure_list, [vol.All(vol.Coerce(int), vol.Range(min = 0, max = 65535))])}

def _get_device(call: ServiceCall):
    if (config_entry := call.hass.config_entries.async_get_entry(async_get(call.hass).async_get(call.data.get(SERVICES_PARAM_DEVICE)).primary_config_entry)) and config_entry.domain == DOMAIN and isinstance(config_entry.runtime_data, Coordinator):
        return config_entry.runtime_data.device
    raise ServiceValidationError("No communication interface for the device found", translation_domain = DOMAIN, translation_key = "no_interface_found")

async def _read_registers(call: ServiceCall, code: int):
    address = call.data.get(SERVICES_PARAM_ADDRESS) or call.data.get(SERVICES_PARAM_REGISTER)
    count = call.data.get(SERVICES_PARAM_COUNT) or call.data.get(SERVICES_PARAM_QUANTITY)
    try:
        if (response := await _get_device(call).execute(code, address, count = count)) is not None:
            for i in range(0, count):
                yield address + i, response[i]
    except Exception as e:
        raise ServiceValidationError(e, translation_domain = DOMAIN, translation_key = "call_failed")

async def _read_holding_registers(call: ServiceCall):
    _LOGGER.debug(f"read_holding_registers: {call}")
    return {k: v async for k, v in _read_registers(call, FUNCTION_CODE.READ_HOLDING_REGISTERS)}

async def _read_input_registers(call: ServiceCall):
    _LOGGER.debug(f"read_input_registers: {call}")
    return {k: v async for k, v in _read_registers(call, FUNCTION_CODE.READ_INPUT_REGISTERS)}

async def _write_single_register(call: ServiceCall):
    _LOGGER.debug(f"write_single_register: {call}")
    try:
        await _get_device(call).execute(FUNCTION_CODE.WRITE_SINGLE_REGISTER, call.data.get(SERVICES_PARAM_ADDRESS) or call.data.get(SERVICES_PARAM_REGISTER), data = call.data.get(SERVICES_PARAM_VALUE))
    except Exception as e:
        raise ServiceValidationError(e, translation_domain = DOMAIN, translation_key = "call_failed")

async def _write_multiple_registers(call: ServiceCall):
    _LOGGER.debug(f"write_multiple_registers: {call}")
    try:
        await _get_device(call).execute(FUNCTION_CODE.WRITE_MULTIPLE_REGISTERS, call.data.get(SERVICES_PARAM_ADDRESS) or call.data.get(SERVICES_PARAM_REGISTER), data = call.data.get(SERVICES_PARAM_VALUES) or call.data.get(SERVICES_PARAM_VALUE))
    except Exception as e:
        raise ServiceValidationError(e, translation_domain = DOMAIN, translation_key = "call_failed")

def register(hass: HomeAssistant):
    _LOGGER.debug("register")
    hass.services.async_register(DOMAIN, SERVICE_READ_HOLDING_REGISTERS, _read_holding_registers, schema = vol.Schema(HEADER_SCHEMA | COUNT_SCHEMA), supports_response = SupportsResponse.OPTIONAL)
    hass.services.async_register(DOMAIN, SERVICE_READ_INPUT_REGISTERS, _read_input_registers, schema = vol.Schema(HEADER_SCHEMA | COUNT_SCHEMA), supports_response = SupportsResponse.OPTIONAL)
    hass.services.async_register(DOMAIN, SERVICE_WRITE_SINGLE_REGISTER, _write_single_register, schema = vol.Schema(HEADER_SCHEMA | VALUE_SCHEMA))
    hass.services.async_register(DOMAIN, SERVICE_WRITE_MULTIPLE_REGISTERS, _write_multiple_registers, schema = vol.Schema(HEADER_SCHEMA | VALUES_SCHEMA))
    hass.services.async_register(DOMAIN, DEPRECATION_SERVICE_WRITE_SINGLE_REGISTER, _write_single_register, schema = vol.Schema(DEPRECATION_HEADER_SCHEMA | VALUE_SCHEMA))
    hass.services.async_register(DOMAIN, DEPRECATION_SERVICE_WRITE_MULTIPLE_REGISTERS, _write_multiple_registers, schema = vol.Schema(DEPRECATION_HEADER_SCHEMA | VALUES_SCHEMA))
