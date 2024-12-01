from __future__ import annotations

import logging

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import *
from .common import *
from .services import *
from .entity import async_add_migrated_entities, create_entity, SolarmanWritableEntity

_LOGGER = logging.getLogger(__name__)

_PLATFORM = get_current_file_name(__name__)

async def async_setup_entry(hass: HomeAssistant, config: ConfigEntry, async_add_entities: AddEntitiesCallback) -> bool:
    _LOGGER.debug(f"async_setup_entry: {config.options}")
    
    coordinator = hass.data[DOMAIN][config.entry_id]
    descriptions = coordinator.inverter.get_entity_descriptions()

    _LOGGER.debug(f"async_setup_entry: async_add_migrated_entities")

    return await async_add_migrated_entities(hass, config, async_add_entities, (create_entity(lambda x: SolarmanSelectEntity(coordinator, x), d) for d in descriptions if is_platform(d, _PLATFORM)))

async def async_unload_entry(hass: HomeAssistant, config: ConfigEntry) -> bool:
    _LOGGER.debug(f"async_unload_entry: {config.options}")

    return True

class SolarmanSelectEntity(SolarmanWritableEntity, SelectEntity):
    def __init__(self, coordinator, sensor):
        SolarmanWritableEntity.__init__(self, coordinator, sensor, _PLATFORM)

        self.mask = display.get("mask") if (display := sensor.get("display")) else None

        if "lookup" in sensor:
            self.dictionary = sensor["lookup"]

        if len(self.registers) > 1:
            _LOGGER.warning(f"SolarmanSelectEntity.__init__: {self._attr_name} contains {len(self.registers)} registers!")

    def get_key(self, value: str):
        if self.dictionary:
            for o in self.dictionary:
                if o["value"] == value and (key := from_bit_index(o["bit"]) if "bit" in o else o["key"]) is not None:
                    return key if not self.mask else self._attr_value & (0xFFFFFFFF - self.mask) | key

        return self.options.index(value)

    @property
    def current_option(self):
        """Return the current option of this select."""
        return self._attr_state if not self.mask else lookup_value(self._attr_value & self.mask, self.dictionary)

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        await self.write(self.get_key(option), option)
