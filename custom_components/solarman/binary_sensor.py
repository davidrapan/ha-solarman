from __future__ import annotations

import logging

from typing import Any

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

def _create_entity(coordinator, description):
    if "artificial" in description:
        match description["artificial"]:
            case "state":
                return SolarmanConnectionSensor(coordinator, description)

    return SolarmanBinarySensorEntity(coordinator, description)

async def async_setup_entry(hass: HomeAssistant, config: ConfigEntry, async_add_entities: AddEntitiesCallback) -> bool:
    _LOGGER.debug(f"async_setup_entry: {config.options}")
    coordinator = hass.data[DOMAIN][config.entry_id]

    descriptions = coordinator.inverter.get_entity_descriptions()

    _LOGGER.debug(f"async_setup: async_add_entities")

    async_add_entities(create_entity(lambda x: _create_entity(coordinator, x), d) for d in descriptions if is_platform(d, _PLATFORM))

    return True

async def async_unload_entry(hass: HomeAssistant, config: ConfigEntry) -> bool:
    _LOGGER.debug(f"async_unload_entry: {config.options}")

    return True

class SolarmanBinarySensorEntity(SolarmanEntity, BinarySensorEntity):
    def __init__(self, coordinator, sensor):
        SolarmanEntity.__init__(self, coordinator, sensor)
        self._sensor_inverted = False
        if "inverted" in sensor and (inverted := sensor["inverted"]):
            self._sensor_inverted = inverted

    @property
    def is_on(self) -> bool | None:
        return (self._attr_state != 0) if not self._sensor_inverted else (self._attr_state == 0)

class SolarmanConnectionSensor(SolarmanBinarySensorEntity):
    def __init__(self, coordinator, sensor):
        super().__init__(coordinator, sensor)
        self._attr_device_class = BinarySensorDeviceClass.CONNECTIVITY 
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

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
        # Maybe set the timestamp using HA's datetime format???
