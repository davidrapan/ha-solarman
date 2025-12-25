from __future__ import annotations

from logging import getLogger
from datetime import datetime, time

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.components.time import TimeEntity, TimeEntityDescription
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import *
from .common import *
from .services import *
from .entity import SolarmanWritableEntity, Coordinator

_LOGGER = getLogger(__name__)

_PLATFORM = get_current_file_name(__name__)

async def async_setup_entry(_: HomeAssistant, config_entry: ConfigEntry[Coordinator], async_add_entities: AddEntitiesCallback) -> bool:
    _LOGGER.debug(f"async_setup_entry: {config_entry.options}")

    async_add_entities(SolarmanTimeEntity(config_entry.runtime_data, d).init() for d in config_entry.runtime_data.device.profile.parser.get_entity_descriptions(_PLATFORM))

    return True

async def async_unload_entry(_: HomeAssistant, config_entry: ConfigEntry[Coordinator]) -> bool:
    _LOGGER.debug(f"async_unload_entry: {config_entry.options}")

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
            _LOGGER.debug(f"SolarmanTimeEntity.native_value of {self._attr_name}: {strepr(e)}")
        return None

    async def async_set_value(self, value: time) -> None:
        """Change the time."""
        await self.write(self._to_native_value(value), value.strftime(TIME_FORMAT))
