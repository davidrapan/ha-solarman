from __future__ import annotations

import logging

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.components.number import NumberEntity, NumberDeviceClass, NumberEntityDescription
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import *
from .common import *
from .services import *
from .entity import SolarmanConfigEntry, create_entity, SolarmanWritableEntity

_LOGGER = logging.getLogger(__name__)

_PLATFORM = get_current_file_name(__name__)

async def async_setup_entry(_: HomeAssistant, config_entry: SolarmanConfigEntry, async_add_entities: AddEntitiesCallback) -> bool:
    _LOGGER.debug(f"async_setup_entry: {config_entry.options}")

    async_add_entities(create_entity(lambda x: SolarmanNumberEntity(config_entry.runtime_data, x), d) for d in postprocess_descriptions(config_entry.runtime_data, _PLATFORM))

    return True

async def async_unload_entry(_: HomeAssistant, config_entry: SolarmanConfigEntry) -> bool:
    _LOGGER.debug(f"async_unload_entry: {config_entry.options}")

    return True

class SolarmanNumberEntity(SolarmanWritableEntity, NumberEntity):
    def __init__(self, coordinator, sensor):
        SolarmanWritableEntity.__init__(self, coordinator, sensor)

        if "mode" in sensor and (mode := sensor["mode"]):
            self._attr_mode = mode

        self.scale = None
        if "scale" in sensor:
            self.scale = get_number(sensor["scale"])

        self.offset = None
        if "offset" in sensor:
            self.offset = get_number(sensor["offset"])

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
