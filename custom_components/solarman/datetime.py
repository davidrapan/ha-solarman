from __future__ import annotations

from logging import getLogger
from zoneinfo import ZoneInfo
from datetime import datetime, timezone

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.components.datetime import DateTimeEntity, DateTimeEntityDescription
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import *
from .common import *
from .services import *
from .entity import SolarmanWritableEntity, Coordinator

_LOGGER = getLogger(__name__)

_PLATFORM = get_current_file_name(__name__)

async def async_setup_entry(_: HomeAssistant, config_entry: ConfigEntry[Coordinator], async_add_entities: AddEntitiesCallback) -> bool:
    _LOGGER.debug(f"async_setup_entry: {config_entry.options}")

    async_add_entities(SolarmanDateTimeEntity(config_entry.runtime_data, d).init() for d in config_entry.runtime_data.device.profile.parser.get_entity_descriptions(_PLATFORM))

    return True

async def async_unload_entry(_: HomeAssistant, config_entry: ConfigEntry[Coordinator]) -> bool:
    _LOGGER.debug(f"async_unload_entry: {config_entry.options}")

    return True

class SolarmanDateTimeEntity(SolarmanWritableEntity, DateTimeEntity):
    def __init__(self, coordinator, sensor):
        SolarmanWritableEntity.__init__(self, coordinator, sensor)

        self._time_zone = ZoneInfo(self.coordinator.hass.config.time_zone)
        self._multiple_registers = len(self.registers) > 3 and self.registers[3] == self.registers[0] + 3

    def _to_native_value(self, value: datetime) -> list:
        # Bug in HA: value set from the device detail page does not have correct tzinfo (set using AUTOMATIONS/ACTIONS works as expected)
        if value.tzinfo == timezone.utc:
            value = value.astimezone(ZoneInfo(self.coordinator.hass.config.time_zone))
        if self._multiple_registers:
            return [value.year - 2000, value.month, value.day, value.hour, value.minute, value.second]
        return [(value.year - 2000 << 8) + value.month, (value.day << 8) + value.hour, (value.minute << 8) + value.second]

    @property
    def native_value(self) -> datetime | None:
        """Return the value reported by the datetime."""
        try:
            if self._attr_native_value:
                return datetime.strptime(self._attr_native_value, DATETIME_FORMAT).replace(tzinfo = ZoneInfo(self.coordinator.hass.config.time_zone))
        except Exception as e:
            _LOGGER.debug(f"SolarmanDateTimeEntity.native_value of {self._attr_name}: {strepr(e)}")
        return None

    async def async_set_value(self, value: datetime) -> None:
        """Change the date/time."""
        await self.write(self._to_native_value(value), value.strftime(DATETIME_FORMAT))
