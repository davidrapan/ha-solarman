from __future__ import annotations

import logging

from zoneinfo import ZoneInfo
from datetime import datetime, time
from functools import cached_property, partial

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.const import EntityCategory
from homeassistant.components.datetime import DateTimeEntity, DateTimeEntityDescription
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

    async_add_entities(create_entity(lambda s: SolarmanDateTimeEntity(coordinator, s), sensor) for sensor in sensors if is_platform(sensor, _PLATFORM))

    return True

async def async_unload_entry(hass: HomeAssistant, config: ConfigEntry) -> bool:
    _LOGGER.debug(f"async_unload_entry: {config.options}")

    return True

class SolarmanDateTimeEntity(SolarmanEntity, DateTimeEntity):
    def __init__(self, coordinator, sensor):
        SolarmanEntity.__init__(self, coordinator, _PLATFORM, sensor)
        if not "control" in sensor:
            self._attr_entity_category = EntityCategory.CONFIG

        self._time_zone = ZoneInfo(self.coordinator.hass.config.time_zone)
        self._multiple_registers = False

        registers = sensor["registers"]
        registers_length = len(registers)
        if registers_length > 0:
            self.register = registers[0]
        if registers_length > 3 and registers[3] == registers[0] + 3:
            self._multiple_registers = True

    @cached_property
    def native_value(self) -> datetime | None:
        """Return the value reported by the datetime."""
        return self._attr_native_value.replace(tzinfo = ZoneInfo(self.coordinator.hass.config.time_zone))

    async def async_set_value(self, value: datetime) -> None:
        """Change the date/time."""
        if await self.coordinator.inverter.call(CODE.WRITE_MULTIPLE_HOLDING_REGISTERS, self.register, get_dt_as_list_int(value.astimezone(ZoneInfo(self.coordinator.hass.config.time_zone)), self._multiple_registers), ACTION_ATTEMPTS_MAX) > 0:
            self.set_state(value)
            self.async_write_ha_state()
