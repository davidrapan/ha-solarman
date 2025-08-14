from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.components.diagnostics import async_redact_data

from .coordinator import Coordinator

TO_REDACT = {"identifiers", "connections", "serial_number", "mac", "device_serial_number_sensor"}

async def async_get_config_entry_diagnostics(_: HomeAssistant, config_entry: ConfigEntry[Coordinator]):
    return {
        "title": config_entry.title,
        "config": async_redact_data(config_entry, TO_REDACT),
        "info": async_redact_data(config_entry.runtime_data.device.info, TO_REDACT),
        "data": async_redact_data(config_entry.runtime_data.data, TO_REDACT)
    }
