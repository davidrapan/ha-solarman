from __future__ import annotations

import logging

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.const import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorDeviceClass

from .const import *
from .common import *
from .services import *
from .entity import SolarmanConfigEntry, create_entity, SolarmanEntity

_LOGGER = logging.getLogger(__name__)

_PLATFORM = get_current_file_name(__name__)

async def async_setup_entry(_: HomeAssistant, config_entry: SolarmanConfigEntry, async_add_entities: AddEntitiesCallback) -> bool:
    _LOGGER.debug(f"async_setup_entry: {config_entry.options}")

    async_add_entities(create_entity(lambda x: SolarmanBinarySensorEntity(config_entry.runtime_data, x), d) for d in postprocess_descriptions(config_entry.runtime_data, _PLATFORM))

    async_add_entities([create_entity(lambda _: SolarmanConnectionSensor(config_entry.runtime_data), None)])

    return True

async def async_unload_entry(_: HomeAssistant, config_entry: SolarmanConfigEntry) -> bool:
    _LOGGER.debug(f"async_unload_entry: {config_entry.options}")

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
    def __init__(self, coordinator):
        super().__init__(coordinator, {"key": "connection_binary_sensor", "name": "Connection"})
        self._attr_device_class = BinarySensorDeviceClass.CONNECTIVITY 
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_state = -1

    @property
    def available(self) -> bool:
        return self._attr_state is not None

    @property
    def is_on(self) -> bool | None:
        return self._attr_state > 0

    def update(self):
        self.set_state(self.coordinator.device.state.value)
        self._attr_extra_state_attributes["updated"] = self.coordinator.device.state.updated.timestamp()
