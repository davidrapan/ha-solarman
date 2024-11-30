from __future__ import annotations

import logging

from datetime import datetime, time

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.components.time import TimeEntity, TimeEntityDescription
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

    async_add_entities(create_entity(lambda x: SolarmanTimeEntity(coordinator, x), d) for d in descriptions if is_platform(d, _PLATFORM))

    return True

async def async_unload_entry(hass: HomeAssistant, config: ConfigEntry) -> bool:
    _LOGGER.debug(f"async_unload_entry: {config.options}")

    return True

class SolarmanTimeEntity(SolarmanWritableEntity, TimeEntity):
    def __init__(self, coordinator, sensor):
        SolarmanWritableEntity.__init__(self, coordinator, sensor)

        self._multiple_registers = len(self.registers) > 1 and self.registers[1] == self.registers[0] + 1
        self._hex = "hex" in sensor
        self._d = (100 if not "dec" in sensor else sensor["dec"]) if not self._hex else (0x100 if sensor["hex"] is None else sensor["hex"])
        self._offset = sensor["offset"] if "offset" in sensor else None

    def _to_native_value(self, value: time) -> int | list:
        if self._hex:
            if self._multiple_registers and self._offset and self._offset >= 0x100: 
                return [concat_hex(div_mod(value.hour, 10)) + self._offset, concat_hex(div_mod(value.minute, 10)) + self._offset]
            return concat_hex((value.hour, value.minute))
        return value.hour * self._d + value.minute if not self._multiple_registers else [value.hour, value.minute]

    @property
    def native_value(self) -> time | None:
        """Return the state of the setting entity."""
        try:
            if self._attr_native_value:
                if isinstance(self._attr_native_value, list) and len(self._attr_native_value) > 1:
                    return datetime.strptime(f"{self._attr_native_value[0]}:{self._attr_native_value[1]}", TIME_FORMAT).time()
                return datetime.strptime(self._attr_native_value, TIME_FORMAT).time()
        except Exception as e:
            _LOGGER.debug(f"SolarmanTimeEntity.native_value of {self._attr_name}: {format_exception(e)}")
        return None

    async def async_set_value(self, value: time) -> None:
        """Change the time."""
        await self.write(self._to_native_value(value), value.strftime(TIME_FORMAT))
