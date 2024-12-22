from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.exceptions import ServiceValidationError

from .const import *
from .coordinator import Inverter, InverterCoordinator

_LOGGER = logging.getLogger(__name__)

HEADER_SCHEMA = {
    vol.Required(SERVICES_PARAM_DEVICE): vol.All(vol.Coerce(str)),
    vol.Required(SERVICES_PARAM_REGISTER): vol.All(vol.Coerce(int), vol.Range(min = 0, max = 65535))
}

QUANTITY_SCHEMA = {
    vol.Required(SERVICES_PARAM_QUANTITY): vol.All(vol.Coerce(int), vol.Range(min = 0, max = 125))
}

VALUE_SCHEMA = {
    vol.Required(SERVICES_PARAM_VALUE): vol.All(vol.Coerce(int), vol.Range(min = 0, max = 65535))
}

VALUES_SCHEMA = {
    vol.Required(SERVICES_PARAM_VALUES): vol.All(cv.ensure_list, [vol.All(vol.Coerce(int), vol.Range(min = 0, max = 65535))])
}

def async_register(hass: HomeAssistant) -> None:
    _LOGGER.debug(f"register")

    def get_device(device_id) -> Inverter:
        device_registry = dr.async_get(hass)
        device = device_registry.async_get(device_id)

        for config_entry in device.config_entries:
            if config_entry in hass.data[DOMAIN] and isinstance(hass.data[DOMAIN][config_entry], InverterCoordinator):
                return hass.data[DOMAIN][config_entry].inverter

        raise ServiceValidationError("No communication interface for device found", translation_domain = DOMAIN, translation_key = "no_interface_found")

    async def read_input_registers(call: ServiceCall) -> int:
        _LOGGER.debug(f"read_input_registers: {call}")

        inverter = get_device(call.data.get(SERVICES_PARAM_DEVICE))
        register = call.data.get(SERVICES_PARAM_REGISTER)
        quantity = call.data.get(SERVICES_PARAM_QUANTITY)
        result = {}

        try:
            if (response := await inverter.call(CODE.READ_INPUT, register, quantity)) is not None:
                for i in range(0, quantity):
                    result[register + i] = response[i]

        except Exception as e:
            raise ServiceValidationError(e, translation_domain = DOMAIN, translation_key = "call_failed")

        return result

    async def read_holding_registers(call: ServiceCall) -> int:
        _LOGGER.debug(f"read_holding_registers: {call}")

        inverter = get_device(call.data.get(SERVICES_PARAM_DEVICE))
        register = call.data.get(SERVICES_PARAM_REGISTER)
        quantity = call.data.get(SERVICES_PARAM_QUANTITY)
        result = {}

        try:
            if (response := await inverter.call(CODE.READ_HOLDING_REGISTERS, register, quantity)) is not None:
                for i in range(0, quantity):
                    result[register + i] = response[i]

        except Exception as e:
            raise ServiceValidationError(e, translation_domain = DOMAIN, translation_key = "call_failed")

        return result

    async def write_single_register(call: ServiceCall) -> None:
        _LOGGER.debug(f"write_single_register: {call}")

        inverter = get_device(call.data.get(SERVICES_PARAM_DEVICE))

        try:
            await inverter.call(CODE.WRITE_SINGLE_REGISTER, call.data.get(SERVICES_PARAM_REGISTER), call.data.get(SERVICES_PARAM_VALUE))
        except Exception as e:
            raise ServiceValidationError(e, translation_domain = DOMAIN, translation_key = "call_failed")

    async def write_multiple_registers(call: ServiceCall) -> None:
        _LOGGER.debug(f"write_multiple_registers: {call}")

        inverter = get_device(call.data.get(SERVICES_PARAM_DEVICE))

        try:
            await inverter.call(CODE.WRITE_MULTIPLE_REGISTERS, call.data.get(SERVICES_PARAM_REGISTER), call.data.get(SERVICES_PARAM_VALUES))
        except Exception as e:
            raise ServiceValidationError(e, translation_domain = DOMAIN, translation_key = "call_failed")

    hass.services.async_register(
        DOMAIN, SERVICE_READ_INPUT_REGISTERS, read_input_registers, schema = vol.Schema(HEADER_SCHEMA | QUANTITY_SCHEMA), supports_response = SupportsResponse.OPTIONAL
    )

    hass.services.async_register(
        DOMAIN, SERVICE_READ_HOLDING_REGISTERS, read_holding_registers, schema = vol.Schema(HEADER_SCHEMA | QUANTITY_SCHEMA), supports_response = SupportsResponse.OPTIONAL
    )

    hass.services.async_register(
        DOMAIN, SERVICE_WRITE_SINGLE_REGISTER, write_single_register, schema = vol.Schema(HEADER_SCHEMA | VALUE_SCHEMA)
    )

    hass.services.async_register(
        DOMAIN, SERVICE_WRITE_MULTIPLE_REGISTERS, write_multiple_registers, schema = vol.Schema(HEADER_SCHEMA | VALUES_SCHEMA)
    )

    hass.services.async_register(
        DOMAIN, DEPRECATION_SERVICE_WRITE_SINGLE_REGISTER, write_single_register, schema = vol.Schema(HEADER_SCHEMA | VALUE_SCHEMA)
    )

    hass.services.async_register(
        DOMAIN, DEPRECATION_SERVICE_WRITE_MULTIPLE_REGISTERS, write_multiple_registers, schema = vol.Schema(HEADER_SCHEMA | VALUES_SCHEMA)
    )
