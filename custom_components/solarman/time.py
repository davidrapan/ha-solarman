from __future__ import annotations

import logging

from datetime import datetime, time
from functools import cached_property, partial

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.const import EntityCategory
from homeassistant.components.time import TimeEntity, TimeEntityDescription
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

    async_add_entities(create_entity(lambda s: SolarmanTimeEntity(coordinator, s), sensor) for sensor in sensors if is_platform(sensor, _PLATFORM))

    return True

async def async_unload_entry(hass: HomeAssistant, config: ConfigEntry) -> bool:
    _LOGGER.debug(f"async_unload_entry: {config.options}")

    return True

class SolarmanTimeEntity(SolarmanEntity, TimeEntity):
    def __init__(self, coordinator, sensor):
        SolarmanEntity.__init__(self, coordinator, _PLATFORM, sensor)
        self._attr_device_class = None
        self._attr_entity_category = EntityCategory.CONFIG

        self._multiple_registers = False

        registers = sensor["registers"]
        registers_length = len(registers)
        if registers_length > 0:
            self.register = registers[0]
        if registers_length > 1 and registers[1] == registers[0] + 1:
            self._multiple_registers = True

    @cached_property
    def native_value(self) -> time | None:
        """Return the state of the setting entity."""
        if not self._attr_native_value:
            return None
        if isinstance(self._attr_native_value, list):
            return datetime.strptime(f"{self._attr_native_value[0]}:{self._attr_native_value[1]}", "%H:%M").time()
        return datetime.strptime(self._attr_native_value, "%H:%M").time()

    async def async_set_value(self, value: time) -> None:
        """Change the time."""
        list_int = [int(value.strftime("%H%M")),] if not self._multiple_registers else [int(value.strftime("%H")), int(value.strftime("%M"))]
        await self.coordinator.inverter.service_write_multiple_holding_registers(self.register, list_int, ACTION_ATTEMPTS_MAX)
        self.set_state(value.strftime("%H:%M"))
        self.async_write_ha_state()
