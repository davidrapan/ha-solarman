from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.exceptions import ServiceValidationError

from .const import *
from .coordinator import Device, Coordinator
from .pysolarman.umodbus.functions import FUNCTION_CODE

_LOGGER = logging.getLogger(__name__)

HEADER_SCHEMA = {
    vol.Required(SERVICES_PARAM_DEVICE): vol.All(vol.Coerce(str)),
    vol.Required(SERVICES_PARAM_ADDRESS): vol.All(vol.Coerce(int), vol.Range(min = 0, max = 65535))
}

DEPRECATION_HEADER_SCHEMA = {
    vol.Required(SERVICES_PARAM_DEVICE): vol.All(vol.Coerce(str)),
    vol.Required(SERVICES_PARAM_REGISTER): vol.All(vol.Coerce(int), vol.Range(min = 0, max = 65535))
}

COUNT_SCHEMA = {
    vol.Required(SERVICES_PARAM_COUNT): vol.All(vol.Coerce(int), vol.Range(min = 0, max = 125))
}

VALUE_SCHEMA = {
    vol.Required(SERVICES_PARAM_VALUE): vol.All(vol.Coerce(int), vol.Range(min = 0, max = 65535))
}

VALUES_SCHEMA = {
    vol.Required(SERVICES_PARAM_VALUES): vol.All(cv.ensure_list, [vol.All(vol.Coerce(int), vol.Range(min = 0, max = 65535))])
}

def async_register(hass: HomeAssistant) -> None:
    _LOGGER.debug(f"register")

    def get_device(device_id) -> Device:
        for config_entry_id in dr.async_get(hass).async_get(device_id).config_entries:
            if (config_entry := hass.config_entries.async_get_entry(config_entry_id)) and config_entry.domain == DOMAIN and config_entry.runtime_data is not None and isinstance(config_entry.runtime_data, Coordinator):
                return config_entry.runtime_data.device
        raise ServiceValidationError("No communication interface for device found", translation_domain = DOMAIN, translation_key = "no_interface_found")

    async def read_registers(call: ServiceCall, code: int):
        device = get_device(call.data.get(SERVICES_PARAM_DEVICE))
        address = call.data.get(SERVICES_PARAM_ADDRESS)
        count = call.data.get(SERVICES_PARAM_COUNT)

        try:
            if (response := await device.exe(code, address = address, count = count)) is not None:
                for i in range(0, count):
                    yield address + i, response[i]
        except Exception as e:
            raise ServiceValidationError(e, translation_domain = DOMAIN, translation_key = "call_failed")

    async def read_holding_registers(call: ServiceCall):
        _LOGGER.debug(f"read_holding_registers: {call}")

        return {k: v async for k, v in read_registers(call, FUNCTION_CODE.READ_HOLDING_REGISTERS)}

    async def read_input_registers(call: ServiceCall):
        _LOGGER.debug(f"read_input_registers: {call}")

        return {k: v async for k, v in read_registers(call, FUNCTION_CODE.READ_INPUT_REGISTERS)}

    async def write_single_register(call: ServiceCall) -> None:
        _LOGGER.debug(f"write_single_register: {call}")

        device = get_device(call.data.get(SERVICES_PARAM_DEVICE))

        try:
            await device.exe(FUNCTION_CODE.WRITE_SINGLE_REGISTER, address = call.data.get(SERVICES_PARAM_ADDRESS, call.data.get(SERVICES_PARAM_REGISTER)), data = call.data.get(SERVICES_PARAM_VALUE))
        except Exception as e:
            raise ServiceValidationError(e, translation_domain = DOMAIN, translation_key = "call_failed")

    async def write_multiple_registers(call: ServiceCall) -> None:
        _LOGGER.debug(f"write_multiple_registers: {call}")

        device = get_device(call.data.get(SERVICES_PARAM_DEVICE))

        try:
            await device.exe(FUNCTION_CODE.WRITE_MULTIPLE_REGISTERS, address = call.data.get(SERVICES_PARAM_ADDRESS, call.data.get(SERVICES_PARAM_REGISTER)), data = call.data.get(SERVICES_PARAM_VALUES))
        except Exception as e:
            raise ServiceValidationError(e, translation_domain = DOMAIN, translation_key = "call_failed")

    hass.services.async_register(
        DOMAIN, SERVICE_READ_HOLDING_REGISTERS, read_holding_registers, schema = vol.Schema(HEADER_SCHEMA | COUNT_SCHEMA), supports_response = SupportsResponse.OPTIONAL
    )

    hass.services.async_register(
        DOMAIN, SERVICE_READ_INPUT_REGISTERS, read_input_registers, schema = vol.Schema(HEADER_SCHEMA | COUNT_SCHEMA), supports_response = SupportsResponse.OPTIONAL
    )

    hass.services.async_register(
        DOMAIN, SERVICE_WRITE_SINGLE_REGISTER, write_single_register, schema = vol.Schema(HEADER_SCHEMA | VALUE_SCHEMA)
    )

    hass.services.async_register(
        DOMAIN, SERVICE_WRITE_MULTIPLE_REGISTERS, write_multiple_registers, schema = vol.Schema(HEADER_SCHEMA | VALUES_SCHEMA)
    )

    hass.services.async_register(
        DOMAIN, DEPRECATION_SERVICE_WRITE_SINGLE_REGISTER, write_single_register, schema = vol.Schema(DEPRECATION_HEADER_SCHEMA | VALUE_SCHEMA)
    )

    hass.services.async_register(
        DOMAIN, DEPRECATION_SERVICE_WRITE_MULTIPLE_REGISTERS, write_multiple_registers, schema = vol.Schema(DEPRECATION_HEADER_SCHEMA | VALUES_SCHEMA)
    )
