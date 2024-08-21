from __future__ import annotations

import logging

from typing import Any
from functools import cached_property, partial

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorDeviceClass

from .const import *
from .common import *
from .services import *
from .entity import create_entity, SolarmanEntity

_LOGGER = logging.getLogger(__name__)

_PLATFORM = get_current_file_name(__name__)

def _create_sensor(coordinator, sensor):
    if "artificial" in sensor:
        match sensor["artificial"]:
            case "state":
                return SolarmanConnectionSensor(coordinator, sensor)

    return SolarmanBinarySensorEntity(coordinator, sensor)

async def async_setup_entry(hass: HomeAssistant, config: ConfigEntry, async_add_entities: AddEntitiesCallback) -> bool:
    _LOGGER.debug(f"async_setup_entry: {config.options}")
    coordinator = hass.data[DOMAIN][config.entry_id]

    sensors = coordinator.inverter.get_sensors()

    _LOGGER.debug(f"async_setup: async_add_entities")

    async_add_entities(create_entity(lambda s: _create_sensor(coordinator, s), sensor) for sensor in sensors if is_platform(sensor, _PLATFORM))

    return True

async def async_unload_entry(hass: HomeAssistant, config: ConfigEntry) -> bool:
    _LOGGER.debug(f"async_unload_entry: {config.options}")

    return True

class SolarmanBinarySensorEntity(SolarmanEntity, BinarySensorEntity):
    def __init__(self, coordinator, sensor):
        SolarmanEntity.__init__(self, coordinator, _PLATFORM, sensor)
        self._sensor_inverted = False
        if "inverted" in sensor and (inverted := sensor["inverted"]):
            self._sensor_inverted = inverted

    @property
    def is_on(self) -> bool | None:
        return (self._attr_state != 0) if not self._sensor_inverted else (self._attr_state == 0)

class SolarmanConnectionSensor(SolarmanBinarySensorEntity):
    def __init__(self, coordinator, sensor):
        super().__init__(coordinator, sensor)
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_device_class = BinarySensorDeviceClass.CONNECTIVITY 

    @property
    def available(self) -> bool:
        return True

    @property
    def is_on(self) -> bool | None:
        if not self._attr_state:
            return None
        return self._attr_state > -1

    def update(self):
        self.set_state(self.coordinator.inverter.state)
        self._attr_extra_state_attributes["updated"] = self.coordinator.inverter.state_updated.strftime("%m/%d/%Y, %H:%M:%S")
