from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.helpers import config_validation as cv, device_registry as dr, entity
from homeassistant.helpers.entity_component import EntityComponent
from homeassistant.exceptions import ServiceValidationError

from .const import *
from .api import Inverter
from .coordinator import InverterCoordinator

_LOGGER = logging.getLogger(__name__)

# Register the services one can invoke on the inverter.
# Apart from this, it also need to be defined in the file 
# services.yaml for the Home Assistant UI in "Developer Tools"

SERVICE_READ_REGISTERS_SCHEMA = vol.Schema(
    {
        vol.Required(SERVICES_PARAM_DEVICE): vol.All(vol.Coerce(str)),
        vol.Required(SERVICES_PARAM_REGISTER): vol.All(vol.Coerce(int), vol.Range(min = 0, max = 65535)),
        vol.Required(SERVICES_PARAM_QUANTITY): vol.All(vol.Coerce(int), vol.Range(min = 0, max = 65535)),
        vol.Required(SERVICES_PARAM_WAIT_FOR_ATTEMPTS): vol.All(vol.Coerce(int), vol.Range(min = 0, max = 30))
    }
)

SERVICE_WRITE_HOLDING_REGISTER_SCHEMA = vol.Schema(
    {
        vol.Required(SERVICES_PARAM_DEVICE): vol.All(vol.Coerce(str)),
        vol.Required(SERVICES_PARAM_REGISTER): vol.All(vol.Coerce(int), vol.Range(min = 0, max = 65535)),
        vol.Required(SERVICES_PARAM_VALUE): vol.All(vol.Coerce(int), vol.Range(min = 0, max = 65535)),
        vol.Required(SERVICES_PARAM_WAIT_FOR_ATTEMPTS): vol.All(vol.Coerce(int), vol.Range(min = 0, max = 30))
    }
)

SERVICE_WRITE_MULTIPLE_HOLDING_REGISTERS_SCHEMA = vol.Schema(
    {
        vol.Required(SERVICES_PARAM_DEVICE): vol.All(vol.Coerce(str)),
        vol.Required(SERVICES_PARAM_REGISTER): vol.All(vol.Coerce(int), vol.Range(min = 0, max = 65535)),
        vol.Required(SERVICES_PARAM_VALUES): vol.All(cv.ensure_list, [vol.All(vol.Coerce(int), vol.Range(min = 0, max = 65535))]),
        vol.Required(SERVICES_PARAM_WAIT_FOR_ATTEMPTS): vol.All(vol.Coerce(int), vol.Range(min = 0, max = 30))
    }
)

def register_services(hass: HomeAssistant) -> None:
    _LOGGER.debug(f"register_services")

    def getDevice(device_id) -> Inverter:
        device_registry = dr.async_get(hass)
        device = device_registry.async_get(device_id)

        for config_entry in device.config_entries:
            if config_entry in hass.data[DOMAIN] and isinstance(hass.data[DOMAIN][config_entry], InverterCoordinator):
                return hass.data[DOMAIN][config_entry].inverter

        return None

    async def read_holding_registers(call: ServiceCall) -> int:
        _LOGGER.debug(f"read_holding_registers: {call}")

        if (inverter := getDevice(call.data.get(SERVICES_PARAM_DEVICE))) is None:
            raise ServiceValidationError(
                "No communication interface for device found",
                translation_domain = DOMAIN,
                translation_key = "no_interface_found"
            )

        register = call.data.get(SERVICES_PARAM_REGISTER)
        quantity = call.data.get(SERVICES_PARAM_QUANTITY)

        try:
            response = await inverter.call(
                CODE.READ_HOLDING_REGISTERS, register, quantity,
                call.data.get(SERVICES_PARAM_WAIT_FOR_ATTEMPTS))
        except Exception as e:
            raise ServiceValidationError(
                e,
                translation_domain = DOMAIN,
                translation_key = "call_failed"
            )

        result = {}

        if response:
            for i in range(0, quantity):
                result[register + i] = response[i]

        return result

    async def read_input_registers(call: ServiceCall) -> int:
        _LOGGER.debug(f"read_input_registers: {call}")

        if (inverter := getDevice(call.data.get(SERVICES_PARAM_DEVICE))) is None:
            raise ServiceValidationError(
                "No communication interface for device found",
                translation_domain = DOMAIN,
                translation_key = "no_interface_found"
            )

        register = call.data.get(SERVICES_PARAM_REGISTER)
        quantity = call.data.get(SERVICES_PARAM_QUANTITY)

        try:
            response = await inverter.call(
                CODE.READ_INPUT, register, quantity,
                call.data.get(SERVICES_PARAM_WAIT_FOR_ATTEMPTS))
        except Exception as e:
            raise ServiceValidationError(
                e,
                translation_domain = DOMAIN,
                translation_key = "call_failed"
            )

        result = {}

        if response:
            for i in range(0, quantity):
                result[register + i] = response[i]

        return result

    async def write_holding_register(call: ServiceCall) -> None:
        _LOGGER.debug(f"write_holding_register: {call}")

        if (inverter := getDevice(call.data.get(SERVICES_PARAM_DEVICE))) is None:
            raise ServiceValidationError(
                "No communication interface for device found",
                translation_domain = DOMAIN,
                translation_key = "no_interface_found",
            )

        try:
            await inverter.call(
                CODE.WRITE_HOLDING_REGISTER,
                call.data.get(SERVICES_PARAM_REGISTER), 
                call.data.get(SERVICES_PARAM_VALUE),
                call.data.get(SERVICES_PARAM_WAIT_FOR_ATTEMPTS))
        except Exception as e:
            raise ServiceValidationError(
                e,
                translation_domain = DOMAIN,
                translation_key = "call_failed"
            )

        return

    async def write_multiple_holding_registers(call: ServiceCall) -> None:
        _LOGGER.debug(f"write_multiple_holding_registers: {call}")

        if (inverter := getDevice(call.data.get(SERVICES_PARAM_DEVICE))) is None:
            raise ServiceValidationError(
                "No communication interface for device found",
                translation_domain = DOMAIN,
                translation_key = "no_interface_found",
            )

        try:
            await inverter.call(
                CODE.WRITE_MULTIPLE_HOLDING_REGISTERS,
                call.data.get(SERVICES_PARAM_REGISTER),
                call.data.get(SERVICES_PARAM_VALUES),
                call.data.get(SERVICES_PARAM_WAIT_FOR_ATTEMPTS))
        except Exception as e:
            raise ServiceValidationError(
                e,
                translation_domain = DOMAIN,
                translation_key = "call_failed"
            )

        return

    hass.services.async_register(
        DOMAIN, SERVICE_READ_HOLDING_REGISTERS, read_holding_registers, schema = SERVICE_READ_REGISTERS_SCHEMA, supports_response = SupportsResponse.OPTIONAL
    )

    hass.services.async_register(
        DOMAIN, SERVICE_READ_INPUT_REGISTERS, read_input_registers, schema = SERVICE_READ_REGISTERS_SCHEMA, supports_response = SupportsResponse.OPTIONAL
    )

    hass.services.async_register(
        DOMAIN, SERVICE_WRITE_HOLDING_REGISTER, write_holding_register, schema = SERVICE_WRITE_HOLDING_REGISTER_SCHEMA
    )

    hass.services.async_register(
        DOMAIN, SERVICE_WRITE_MULTIPLE_HOLDING_REGISTERS, write_multiple_holding_registers, schema = SERVICE_WRITE_MULTIPLE_HOLDING_REGISTERS_SCHEMA
    )

    return

def remove_services(hass: HomeAssistant) -> None:
    _LOGGER.debug(f"remove_services")

    hass.services.async_remove(DOMAIN, SERVICE_READ_HOLDING_REGISTERS)
    hass.services.async_remove(DOMAIN, SERVICE_READ_INPUT_REGISTERS)
    hass.services.async_remove(DOMAIN, SERVICE_WRITE_HOLDING_REGISTER)
    hass.services.async_remove(DOMAIN, SERVICE_WRITE_MULTIPLE_HOLDING_REGISTERS)

    return
