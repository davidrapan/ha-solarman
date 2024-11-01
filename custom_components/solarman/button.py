from __future__ import annotations

import logging

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.components.button import ButtonEntity, ButtonDeviceClass, ButtonEntityDescription
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import *
from .common import *
from .services import *
from .entity import create_entity, SolarmanWritableEntity

_LOGGER = logging.getLogger(__name__)

_PLATFORM = get_current_file_name(__name__)

async def async_setup_entry(hass: HomeAssistant, config: ConfigEntry, async_add_entities: AddEntitiesCallback) -> bool:
    _LOGGER.debug(f"async_setup_entry: {config.options}")
    coordinator = hass.data[DOMAIN][config.entry_id]

    descriptions = coordinator.inverter.get_entity_descriptions()

    _LOGGER.debug(f"async_setup: async_add_entities")

    async_add_entities(create_entity(lambda x: SolarmanButtonEntity(coordinator, x), d) for d in descriptions if is_platform(d, _PLATFORM))

    return True

async def async_unload_entry(hass: HomeAssistant, config: ConfigEntry) -> bool:
    _LOGGER.debug(f"async_unload_entry: {config.options}")

    return True

class SolarmanButtonEntity(SolarmanWritableEntity, ButtonEntity):
    def __init__(self, coordinator, sensor):
        SolarmanWritableEntity.__init__(self, coordinator, _PLATFORM, sensor)

        self._value = 1
        if "value" in sensor and (value := sensor["value"]):
            if True in value:
                self._value = value[True]
            if "on" in value:
                self._value = value["on"]

        if self.registers_length > 1:
            _LOGGER.warning(f"SolarmanButtonEntity.__init__: {self._attr_name} contains {self.registers_length} registers!")

    async def async_press(self) -> None:
        """Handle the button press."""
        await self.write(self._value)
