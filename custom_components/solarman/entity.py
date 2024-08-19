from __future__ import annotations

import logging

from typing import Any
from functools import cached_property, partial

from homeassistant.core import callback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.typing import UNDEFINED, StateType, UndefinedType

from .const import *
from .common import *
from .services import *
from .coordinator import InverterCoordinator

_LOGGER = logging.getLogger(__name__)

def create_entity(creator, sensor):
    try:
        entity = creator(sensor)

        entity.update()

        return entity
    except BaseException as e:
        _LOGGER.error(f"Configuring {sensor} failed. [{format_exception(e)}]")
        raise

class SolarmanCoordinatorEntity(CoordinatorEntity[InverterCoordinator]):
    def __init__(self, coordinator: InverterCoordinator):
        super().__init__(coordinator)
        self._attr_device_info = self.coordinator.inverter.device_info
        self._attr_extra_state_attributes = {}

    @property
    def available(self) -> bool:
        return self._attr_available and self.coordinator.inverter.available()

    @callback
    def _handle_coordinator_update(self) -> None:
        self.update()
        self.async_write_ha_state()

    def get_data_state(self, name):
        return self.coordinator.data[name]["state"]

    def get_data_value(self, name):
        return self.coordinator.data[name]["value"]

    def get_data(self, name, default):
        if name in self.coordinator.data:
                return self.get_data_state(name)

        return default

    def set_state(self, state):
        self._attr_state = state

    def update(self):
        if self.sensor_name in self.coordinator.data and (data := self.coordinator.data[self.sensor_name]):
            self.set_state(data["state"])
            if "value" in data:
                self._attr_extra_state_attributes["value"] = data["value"]
            if self.attributes:
                for attr in filter(lambda a: a in self.coordinator.data, self.attributes):
                    self._attr_extra_state_attributes[attr.replace(f"{self.sensor_name} ", "")] = self.get_data_state(attr)

class SolarmanEntity(SolarmanCoordinatorEntity):
    def __init__(self, coordinator, platform, sensor):
        super().__init__(coordinator)
        self.sensor_name = sensor["name"]
        self.sensor_friendly_name = sensor[ATTR_FRIENDLY_NAME] if ATTR_FRIENDLY_NAME in sensor else self.sensor_name
        self.sensor_entity_id = sensor["entity_id"] if "entity_id" in sensor else None
        self.sensor_unique_id = self.sensor_entity_id if self.sensor_entity_id else self.sensor_name

        self._attr_entity_registry_enabled_default = not "disabled" in sensor

        self._attr_name = "{} {}".format(self.coordinator.inverter.name, self.sensor_name) if self.sensor_name else self.coordinator.inverter.name

        self._attr_friendly_name = "{} {}".format(self.coordinator.inverter.name, self.sensor_friendly_name) if self.sensor_friendly_name else self.coordinator.inverter.name

        self._attr_unique_id = "{}_{}_{}".format(self.coordinator.inverter.name, self.coordinator.inverter.serial, self.sensor_unique_id) if self.sensor_unique_id else "{}_{}".format(self.coordinator.inverter.name, self.coordinator.inverter.serial)

        if self.sensor_entity_id:
            self.entity_id = "{}.{}_{}".format(platform, self.coordinator.inverter.name, self.sensor_entity_id)
        if "icon" in sensor and (icon := sensor["icon"]):
            self._attr_icon = icon
        if "category" in sensor and (entity_category := sensor["category"]):
            self._attr_entity_category = entity_category
        if "class" in sensor and (device_class := sensor["class"]):
            self._attr_device_class = device_class
        if "device_class" in sensor and (device_class := sensor["device_class"]):
            self._attr_device_class = device_class
        if "state_class" in sensor and (state_class := sensor["state_class"]):
            self._attr_state_class = state_class
        if "uom" in sensor and (unit_of_measurement := sensor["uom"]):
            self._attr_native_unit_of_measurement = unit_of_measurement
        if "unit_of_measurement" in sensor and (unit_of_measurement := sensor["unit_of_measurement"]):
            self._attr_native_unit_of_measurement = unit_of_measurement
        if "suggested_display_precision" in sensor and (display_precision := sensor["suggested_display_precision"]):
            self._attr_suggested_display_precision = display_precision
        if "options" in sensor and (options := sensor["options"]):
            self._attr_options = options
            self._attr_extra_state_attributes = self._attr_extra_state_attributes | { "options": options }
        elif "lookup" in sensor and "rule" in sensor and 0 < sensor["rule"] < 5 and (options := [s["value"] for s in sensor["lookup"]]):
            self._attr_device_class = "enum"
            self._attr_options = options
            self._attr_extra_state_attributes = self._attr_extra_state_attributes | { "options": options }
        if "alt" in sensor and (alt := sensor["alt"]):
            self._attr_extra_state_attributes = self._attr_extra_state_attributes | { "Alt Name": alt }
        if "description" in sensor and (description := sensor["description"]):
            self._attr_extra_state_attributes = self._attr_extra_state_attributes | { "description": description }

        self.attributes = sensor["attributes"] if "attributes" in sensor else None

    def _friendly_name_internal(self) -> str | None:
        """Return the friendly name of the device."""
        return self._attr_friendly_name
