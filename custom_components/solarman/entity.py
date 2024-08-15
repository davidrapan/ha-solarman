from __future__ import annotations

import logging
import asyncio
import voluptuous as vol

from functools import cached_property, partial

from homeassistant.components.template.sensor import SensorTemplate
from homeassistant.components.template.sensor import TriggerSensorEntity
from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.helpers.template import Template

from homeassistant.core import HomeAssistant, callback
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME, EntityCategory, STATE_OFF, STATE_ON
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo, format_mac
from homeassistant.helpers.entity import Entity, ToggleEntity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.typing import UNDEFINED, StateType, UndefinedType

from .const import *
from .common import *
from .services import *
from .api import Inverter
from .discovery import InverterDiscovery
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

    def update(self):
        c = len(self.coordinator.data)
        if c > 1 or (c == 1 and self.sensor_name in self.coordinator.data):
            if self.sensor_name in self.coordinator.data:
                self._attr_state = self.get_data_state(self.sensor_name)
                if "value" in self.coordinator.data[self.sensor_name]:
                    self._attr_extra_state_attributes["value"] = self.get_data_value(self.sensor_name)
                if self.attributes:
                    for attr in self.attributes:
                        if attr in self.coordinator.data:
                            attr_name = attr.replace(f"{self.sensor_name} ", "")
                            self._attr_extra_state_attributes[attr_name] = self.get_data_state(attr)

class SolarmanEntity(SolarmanCoordinatorEntity):
    def __init__(self, coordinator, platform, sensor):
        super().__init__(coordinator)
        self.sensor_name = sensor["name"]
        self.sensor_friendly_name = sensor[ATTR_FRIENDLY_NAME] if ATTR_FRIENDLY_NAME in sensor else self.sensor_name
        self.sensor_entity_id = sensor["entity_id"] if "entity_id" in sensor else None
        self.sensor_unique_id = self.sensor_entity_id if self.sensor_entity_id else self.sensor_name

        if self.sensor_entity_id:
            self.entity_id = "{}.{}_{}".format(platform, self.coordinator.inverter.name, self.sensor_entity_id)

        # Set the enabled default value
        self._attr_entity_registry_enabled_default = not "disabled" in sensor

        # Set the category of the sensor.
        self._attr_entity_category = (None)

        # Set the name of the sensor.
        self._attr_name = "{} {}".format(self.coordinator.inverter.name, self.sensor_name)

        # Set the friendly name of the sensor.
        self._attr_friendly_name = "{} {}".format(self.coordinator.inverter.name, self.sensor_friendly_name)

        # Set a unique_id based on the serial number
        self._attr_unique_id = "{}_{}_{}".format(self.coordinator.inverter.name, self.coordinator.inverter.serial, self.sensor_unique_id)

        # Set the icon of the sensor.
        self._attr_icon = sensor["icon"] if "icon" in sensor else None

        if "class" in sensor and (device_class := sensor["class"]):
            self._attr_device_class = device_class
        if "device_class" in sensor and (device_class := sensor["device_class"]):
            self._attr_device_class = device_class
        if "state_class" in sensor and (state_class := sensor["state_class"]):
            self._attr_extra_state_attributes = { "state_class": state_class }
        if "uom" in sensor and (unit_of_measurement := sensor["uom"]):
            self._attr_unit_of_measurement = unit_of_measurement
        if "unit_of_measurement" in sensor and (unit_of_measurement := sensor["unit_of_measurement"]):
            self._attr_unit_of_measurement = unit_of_measurement
        if "suggested_display_precision" in sensor and (display_precision := sensor["suggested_display_precision"]):
            self._attr_suggested_display_precision = display_precision
        if "options" in sensor and (options := sensor["options"]):
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
