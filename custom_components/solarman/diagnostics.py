from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.components.diagnostics import async_redact_data

from . import SolarmanConfigEntry

TO_REDACT = {"mac", "serial_number"}

async def async_get_config_entry_diagnostics(_: HomeAssistant, config_entry: SolarmanConfigEntry) -> dict[str, Any]:
    return {
        "entry": {
            "title": config_entry.title,
            "config": async_redact_data(config_entry, TO_REDACT),
            "device_info": async_redact_data(config_entry.runtime_data.device.info, TO_REDACT),
        },
        "data": config_entry.runtime_data.data
    }
