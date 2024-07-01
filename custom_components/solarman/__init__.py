from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry

from .const import *
from .config_flow import async_update_listener

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    _LOGGER.debug(f"async_setup_entry({entry.as_dict()})")
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_update_listener))
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    _LOGGER.debug(f"async_unload_entry({entry.as_dict()})")
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        _ = hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
