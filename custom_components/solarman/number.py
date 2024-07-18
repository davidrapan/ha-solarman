from __future__ import annotations

import logging
import asyncio
import voluptuous as vol

from functools import cached_property, partial

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.const import CONF_NAME, STATE_OFF, STATE_ON, EntityCategory
from homeassistant.components.number import NumberEntity, NumberDeviceClass, NumberEntityDescription
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import *
from .common import *
from .services import *
from .sensor import SolarmanSensor

_LOGGER = logging.getLogger(__name__)

_PLATFORM = get_current_file_name(__name__)

def _create_sensor(coordinator, sensor):
    try:
        entity = SolarmanNumberEntity(coordinator, sensor)

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

    async_add_entities(_create_sensor(coordinator, sensor) for sensor in sensors if "configurable" in sensor)
    #if ("class" in sensor and sensor["class"] == _PLATFORM)
    return True

async def async_unload_entry(hass: HomeAssistant, config: ConfigEntry) -> bool:
    _LOGGER.debug(f"async_unload_entry: {config.options}")
    return True

class SolarmanNumberEntity(SolarmanSensor, NumberEntity):
    def __init__(self, coordinator, sensor):
        SolarmanSensor.__init__(self, coordinator, sensor, 0, 0)
        # Set The Category of the entity.
        self._attr_entity_category = EntityCategory.CONFIG

        self.scale = 1
        if "scale" in sensor:
            self.scale = get_numbe(sensor["scale"])

        registers = sensor["registers"]
        registers_length = len(registers)
        if registers_length > 0:
            self.register = sensor["registers"][0]
        if registers_length > 1:
            _LOGGER.warning(f"SolarmanNumberEntity.__init__: Contains more than 1 register!")

        configurable = sensor["configurable"]
        if "min" in configurable:
            self._attr_native_min_value = configurable["min"]
        if "max" in configurable:
            self._attr_native_max_value = configurable["max"]
        if "step" in configurable:
            self._attr_native_step = configurable["step"]

    @property
    def native_value(self) -> float:
        """Return the state of the setting entity."""
        return self._attr_state

    async def async_set_native_value(self, value: float) -> None:
        """Update the setting."""
        await self.coordinator.inverter.service_write_multiple_holding_registers(self.register, [int(value / self.scale),])
        self._attr_state = get_numbe(value)
        self.async_write_ha_state()
        #await self.entity_description.update_fn(self.coordinator., int(value))
        #await self.coordinator.async_request_refresh()
