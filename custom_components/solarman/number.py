from __future__ import annotations

import logging

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.components.number import NumberEntity, NumberDeviceClass, NumberEntityDescription
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

    async_add_entities(create_entity(lambda x: SolarmanNumberEntity(coordinator, x), d) for d in descriptions if is_platform(d, _PLATFORM) or "configurable" in d)

    return True

async def async_unload_entry(hass: HomeAssistant, config: ConfigEntry) -> bool:
    _LOGGER.debug(f"async_unload_entry: {config.options}")

    return True

class SolarmanNumberEntity(SolarmanWritableEntity, NumberEntity):
    def __init__(self, coordinator, sensor):
        SolarmanWritableEntity.__init__(self, coordinator, _PLATFORM, sensor)

        if "mode" in sensor and (mode := sensor["mode"]):
            self._attr_mode = mode

        self.scale = None
        if "scale" in sensor:
            self.scale = get_number(sensor["scale"])

        self.offset = None
        if "offset" in sensor:
            self.offset = get_number(sensor["offset"])

        if self.registers_length > 1:
            _LOGGER.warning(f"SolarmanNumberEntity.__init__: {self._attr_name} contains {self.registers_length} registers!")

        if "configurable" in sensor and (configurable := sensor["configurable"]):
            if "mode" in configurable:
                self._attr_mode = configurable["mode"]
            if "min" in configurable:
                self._attr_native_min_value = configurable["min"]
            if "max" in configurable:
                self._attr_native_max_value = configurable["max"]
            if "step" in configurable:
                self._attr_native_step = configurable["step"]

        if not hasattr(self, "_attr_native_min_value") and not hasattr(self, "_attr_native_max_value") and "range" in sensor and (range := sensor["range"]):
            self._attr_native_min_value = range["min"]
            self._attr_native_max_value = range["max"]
            if self.scale is not None:
                self._attr_native_min_value *= self.scale
                self._attr_native_max_value *= self.scale

    async def async_set_native_value(self, value: float) -> None:
        """Update the setting."""
        value_int = int(value if self.scale is None else value / self.scale)
        if self.offset is not None:
            value_int += self.offset
        await self.write(value_int if value_int < 0xFFFF else 0xFFFF, get_number(value))
