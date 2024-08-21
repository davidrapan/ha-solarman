from __future__ import annotations

import logging

from typing import Any
from functools import cached_property, partial

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.const import EntityCategory
from homeassistant.components.number import NumberEntity, NumberDeviceClass, NumberEntityDescription
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

    async_add_entities(create_entity(lambda s: SolarmanNumberEntity(coordinator, s), sensor) for sensor in sensors if is_platform(sensor, _PLATFORM) or "configurable" in sensor)

    return True

async def async_unload_entry(hass: HomeAssistant, config: ConfigEntry) -> bool:
    _LOGGER.debug(f"async_unload_entry: {config.options}")

    return True

class SolarmanNumberEntity(SolarmanEntity, NumberEntity):
    def __init__(self, coordinator, sensor):
        SolarmanEntity.__init__(self, coordinator, _PLATFORM, sensor)
        self._attr_entity_category = EntityCategory.CONFIG

        self.scale = 1
        if "scale" in sensor:
            self.scale = get_number(sensor["scale"])

        registers = sensor["registers"]
        registers_length = len(registers)
        if registers_length > 0:
            self.register = sensor["registers"][0]
        if registers_length > 1:
            _LOGGER.warning(f"SolarmanNumberEntity.__init__: Contains more than 1 register!")

        if "configurable" in sensor and (configurable := sensor["configurable"]):
            if "min" in configurable:
                self._attr_native_min_value = configurable["min"]
            if "max" in configurable:
                self._attr_native_max_value = configurable["max"]
            if "step" in configurable:
                self._attr_native_step = configurable["step"]
        elif "range" in sensor and (range := sensor["range"]):
            self._attr_native_min_value = range["min"]
            self._attr_native_max_value = range["max"]

    async def async_set_native_value(self, value: float) -> None:
        """Update the setting."""
        await self.coordinator.inverter.service_write_multiple_holding_registers(self.register, [int(value / self.scale),], ACTION_ATTEMPTS_MAX)
        self.set_state(get_number(value))
        self.async_write_ha_state()
        #await self.entity_description.update_fn(self.coordinator., int(value))
        #await self.coordinator.async_request_refresh()
