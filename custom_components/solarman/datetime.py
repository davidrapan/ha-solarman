from __future__ import annotations

import logging

from zoneinfo import ZoneInfo
from datetime import datetime, timezone

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

    descriptions = coordinator.inverter.get_entity_descriptions()

    _LOGGER.debug(f"async_setup: async_add_entities")

    async_add_entities(create_entity(lambda x: SolarmanDateTimeEntity(coordinator, x), d) for d in descriptions if is_platform(d, _PLATFORM))

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

    @property
    def native_value(self) -> datetime | None:
        """Return the value reported by the datetime."""
        try:
            if self._attr_native_value:
                return datetime.strptime(self._attr_native_value, DATETIME_FORMAT).replace(tzinfo = ZoneInfo(self.coordinator.hass.config.time_zone))
        except Exception as e:
            _LOGGER.debug(f"SolarmanDateTimeEntity.native_value: {format_exception(e)}")
        return None

    async def async_set_value(self, value: datetime) -> None:
        """Change the date/time."""
        # Value set from the device detail page does not have correct tzinfo (set using ACTIONS works as expected)
        if value.tzinfo == timezone.utc:
            value = value.astimezone(ZoneInfo(self.coordinator.hass.config.time_zone))
        if await self.coordinator.inverter.call(CODE.WRITE_MULTIPLE_HOLDING_REGISTERS, self.register, get_dt_as_list_int(value, self._multiple_registers), ACTION_ATTEMPTS_MAX) > 0:
            self.set_state(value.strftime(DATETIME_FORMAT))
            self.async_write_ha_state()
