from __future__ import annotations

import logging
import asyncio
import voluptuous as vol

from datetime import datetime, time
from functools import cached_property, partial

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.const import CONF_NAME, STATE_OFF, STATE_ON, EntityCategory
from homeassistant.components.time import TimeEntity, TimeEntityDescription
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import *
from .common import *
from .services import *
from .sensor import SolarmanSensor

_LOGGER = logging.getLogger(__name__)

_PLATFORM = get_current_file_name(__name__)

def _create_sensor(coordinator, sensor):
    try:
        entity = SolarmanTimeEntity(coordinator, sensor)

        entity.update()

        return entity
    except BaseException as e:
        _LOGGER.error(f"Configuring {sensor} failed. [{format_exception(e)}]")
        raise

async def async_setup_entry(hass: HomeAssistant, config: ConfigEntry, async_add_entities: AddEntitiesCallback) -> bool:
    _LOGGER.debug(f"async_setup_entry: {config.options}")
    coordinator = hass.data[DOMAIN][config.entry_id]

    sensors = coordinator.inverter.get_sensors()

    # Add entities.
    #
    _LOGGER.debug(f"async_setup: async_add_entities")

    async_add_entities(_create_sensor(coordinator, sensor) for sensor in sensors if ("class" in sensor and sensor["class"] == _PLATFORM))

    return True

async def async_unload_entry(hass: HomeAssistant, config: ConfigEntry) -> bool:
    _LOGGER.debug(f"async_unload_entry: {config.options}")

    return True

class SolarmanTimeEntity(SolarmanSensor, TimeEntity):
    def __init__(self, coordinator, sensor):
        SolarmanSensor.__init__(self, coordinator, sensor, 0, 0)
        # Set The Device Class of the entity.
        self._attr_device_class = None
        # Set The Category of the entity.
        self._attr_entity_category = EntityCategory.CONFIG

        registers = sensor["registers"]
        registers_length = len(registers)
        if registers_length > 0:
            self.register = sensor["registers"][0]
        if registers_length > 1:
            _LOGGER.warning(f"SolarmanTimeEntity.__init__: Contains more than 1 register!")

    @cached_property
    def native_value(self) -> float:
        """Return the state of the setting entity."""
        return datetime.strptime(self._attr_state, "%H:%M").time()

    async def async_set_value(self, value: time) -> None:
        """Change the time."""
        value_int = int(value.strftime("%H%M"))
        await self.coordinator.inverter.service_write_multiple_holding_registers(self.register, [value_int,], ACTION_ATTEMPTS_MAX)
        self._attr_state = value_int
        self.async_write_ha_state()
