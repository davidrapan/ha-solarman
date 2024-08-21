from __future__ import annotations

import logging

from typing import Any
from functools import cached_property, partial

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.const import EntityCategory
from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import *
from .common import *
from .services import *
from .entity import create_entity, SolarmanEntity

_LOGGER = logging.getLogger(__name__)

_PLATFORM = get_current_file_name(__name__)

async def async_setup_entry(hass: HomeAssistant, config: ConfigEntry, async_add_entities: AddEntitiesCallback) -> bool:
    _LOGGER.debug(f"async_setup_entry: {config.options}")
    coordinator = hass.data[DOMAIN][config.entry_id]

    sensors = coordinator.inverter.get_sensors()

    _LOGGER.debug(f"async_setup: async_add_entities")

    async_add_entities(create_entity(lambda s: SolarmanSelectEntity(coordinator, s), sensor) for sensor in sensors if is_platform(sensor, _PLATFORM))

    return True

async def async_unload_entry(hass: HomeAssistant, config: ConfigEntry) -> bool:
    _LOGGER.debug(f"async_unload_entry: {config.options}")

    return True

class SolarmanSelectEntity(SolarmanEntity, SelectEntity):
    def __init__(self, coordinator, sensor):
        SolarmanEntity.__init__(self, coordinator, _PLATFORM, sensor)
        self._attr_entity_category = EntityCategory.CONFIG

        if "lookup" in sensor:
            self.dictionary = sensor["lookup"]

        registers = sensor["registers"]
        registers_length = len(registers)
        if registers_length > 0:
            self.register = sensor["registers"][0]
        if registers_length > 1:
            _LOGGER.warning(f"SolarmanSelectEntity.__init__: Contains more than 1 register!")

    def get_key(self, value: str):
        if self.dictionary:
            for o in self.dictionary:
                if o["value"] == value:
                    return o["key"]

        return self.options.index(value)

    @property
    def current_option(self):
        """Return the current option of this select."""
        if not self._attr_state:
            return None
        return self._attr_state

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        await self.coordinator.inverter.service_write_multiple_holding_registers(self.register, [self.get_key(option),], ACTION_ATTEMPTS_MAX)
        self.set_state(option)
        self.async_write_ha_state()
