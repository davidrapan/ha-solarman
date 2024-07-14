from __future__ import annotations

import voluptuous as vol

from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv

from .const import *
from .api import Inverter

# Register the services one can invoke on the inverter.
# Apart from this, it also need to be defined in the file 
# services.yaml for the Home Assistant UI in "Developer Tools"

SERVICE_WRITE_REGISTER_SCHEMA = vol.Schema(
    {
        vol.Required(SERVICES_PARAM_REGISTER): vol.All(vol.Coerce(int), vol.Range(min = 0, max = 65535)),
        vol.Required(SERVICES_PARAM_VALUE): vol.All(vol.Coerce(int), vol.Range(min = 0, max = 65535)),
    }
)

SERVICE_WRITE_MULTIPLE_REGISTERS_SCHEMA = vol.Schema(
    {
        vol.Required(SERVICES_PARAM_REGISTER): vol.All(vol.Coerce(int), vol.Range(min = 0, max = 65535)),
        vol.Required(SERVICES_PARAM_VALUES): vol.All(cv.ensure_list, [vol.All(vol.Coerce(int), vol.Range(min = 0, max = 65535))]),
    }
)

def register_services(hass: HomeAssistant, inverter: Inverter):
    async def write_holding_register(call) -> None:
        await inverter.service_write_holding_register(
            register = call.data.get(SERVICES_PARAM_REGISTER), 
            value = call.data.get(SERVICES_PARAM_VALUE))
        return

    async def write_multiple_holding_registers(call) -> None:
        await inverter.service_write_multiple_holding_registers(
            register = call.data.get(SERVICES_PARAM_REGISTER),
            values = call.data.get(SERVICES_PARAM_VALUES))
        return

    hass.services.async_register(
        DOMAIN, SERVICE_WRITE_REGISTER, write_holding_register, schema = SERVICE_WRITE_REGISTER_SCHEMA
    )

    hass.services.async_register(
        DOMAIN, SERVICE_WRITE_MULTIPLE_REGISTERS, write_multiple_holding_registers, schema = SERVICE_WRITE_MULTIPLE_REGISTERS_SCHEMA
    )

def remove_services(hass: HomeAssistant):
    hass.services.async_remove(DOMAIN, SERVICE_WRITE_REGISTER)
    hass.services.async_remove(DOMAIN, SERVICE_WRITE_MULTIPLE_REGISTERS)
