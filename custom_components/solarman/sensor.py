from __future__ import annotations

import re
import logging
import asyncio
import voluptuous as vol

from homeassistant.core import HomeAssistant, callback
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME, EntityCategory
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo, format_mac
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import *
from .common import *
from .api import Inverter
from .discovery import InverterDiscovery
from .coordinator import InverterCoordinator
from .services import *

_LOGGER = logging.getLogger(__name__)

def _create_sensor(coordinator, sensor, battery_life_cycle_rating):
    try:
        if "artificial" in sensor:
            entity = SolarmanStatus(coordinator, sensor)
        elif "isstr" in sensor:
            entity = SolarmanSensorBase(coordinator, sensor)
        else:
            entity = SolarmanSensor(coordinator, sensor, battery_life_cycle_rating)

        entity.update()

        return entity
    except BaseException as e:
        _LOGGER.error(f"Configuring {sensor} failed. [{format_exception(e)}]")
        raise

async def async_setup(hass: HomeAssistant, config, async_add_entities: AddEntitiesCallback, id = None):
    _LOGGER.debug(f"async_setup: {config}")

    inverter_name = config.get(CONF_NAME)
    inverter_discovery = config.get(CONF_INVERTER_DISCOVERY)
    inverter_host = config.get(CONF_INVERTER_HOST)
    inverter_serial = config.get(CONF_INVERTER_SERIAL)
    inverter_port = config.get(CONF_INVERTER_PORT)
    inverter_mb_slave_id = config.get(CONF_INVERTER_MB_SLAVE_ID)
    lookup_path = hass.config.path(LOOKUP_DIRECTORY_PATH)
    lookup_file = config.get(CONF_LOOKUP_FILE)
    battery_life_cycle_rating = config.get(CONF_BATTERY_LIFE_CYCLE_RATING)

    inverter_discovery = InverterDiscovery(hass, inverter_host)

    if inverter_discovery:
        if inverter_host_scanned := await inverter_discovery.get_ip():
            inverter_host = inverter_host_scanned

    if inverter_serial == 0:
        if inverter_serial_scanned := await inverter_discovery.get_serial():
            inverter_serial = inverter_serial_scanned

    inverter_mac = await inverter_discovery.get_mac()

    if not inverter_mb_slave_id:
        inverter_mb_slave_id = DEFAULT_INVERTER_MB_SLAVE_ID

    if inverter_host is None:
        raise vol.Invalid("configuration parameter [inverter_host] does not have a value")
    if inverter_serial is None:
        raise vol.Invalid("configuration parameter [inverter_serial] does not have a value")

    inverter = Inverter(inverter_host, inverter_serial, inverter_port, inverter_mb_slave_id, inverter_name, inverter_mac, lookup_path, lookup_file)
    sensors = await inverter.get_sensors()

    coordinator = InverterCoordinator(hass, inverter)

    # Fetch initial data so we have data when entities subscribe.
    #
    # If the refresh fails, async_config_entry_first_refresh will
    # raise ConfigEntryNotReady and setup will try again later.
    #
    # If you do not want to retry setup on failure, use
    # coordinator.async_refresh() instead.
    #
    _LOGGER.debug(f"async_setup: coordinator.async_config_entry_first_refresh")

    await coordinator.async_config_entry_first_refresh()

    # Add entities.
    #
    _LOGGER.debug(f"async_setup: async_add_entities")

    async_add_entities(_create_sensor(coordinator, sensor, battery_life_cycle_rating) for sensor in sensors)

    # Register the services with home assistant.
    #
    _LOGGER.debug(f"async_setup: register_services")
    
    hass.data.setdefault(DOMAIN, {})[id] = coordinator

    register_services(hass, inverter)

async def async_setup_entry(hass: HomeAssistant, config: ConfigEntry, async_add_entities: AddEntitiesCallback) -> bool:
    _LOGGER.debug(f"async_setup_entry: {config.options}")
    await async_setup(hass, config.options, async_add_entities, config.entry_id)
    return True

async def async_unload_entry(hass: HomeAssistant, config: ConfigEntry) -> bool:
    _LOGGER.debug(f"async_unload_entry: {config.options}")
    remove_services(hass)
    return True

class SolarmanCoordinatorEntity(CoordinatorEntity[InverterCoordinator]):
    def __init__(self, coordinator: InverterCoordinator, name: str = None):
        super().__init__(coordinator)
        self.model = self.coordinator.inverter.lookup_file.replace(".yaml", "")

        if '_' in self.model:
            dev_man = self.model.split('_')
            self.manufacturer = dev_man[0].capitalize()
            self.model = dev_man[1].upper()

        self._attr_device_info = {
            "connections": {(CONNECTION_NETWORK_MAC, format_mac(self.coordinator.inverter.mac))}
        } if self.coordinator.inverter.mac else {} | {
            "identifiers": {(DOMAIN, self.coordinator.inverter.serial)},
            "name": self.coordinator.inverter.name,
            "manufacturer": self.manufacturer,
            "model": self.model,
            "serial_number": self.coordinator.inverter.serial
        }

        #self._attr_extra_state_attributes = { "id": self.coordinator.inverter.serial, "integration": DOMAIN }
        self._attr_extra_state_attributes = {}

class SolarmanStatus(SolarmanCoordinatorEntity):
    def __init__(self, coordinator, sensor):
        super().__init__(coordinator)
        self.sensor_name = sensor["name"]

        #  Return the category of the sensor.
        self._attr_entity_category = (EntityCategory.DIAGNOSTIC)

        #  Return the icon of the sensor.
        self._attr_icon = "mdi:information"

        #  Return the name of the sensor.
        self._attr_name = "{} {}".format(self.coordinator.inverter.name, self.sensor_name)

        #  Return a unique_id based on the serial number
        self._attr_unique_id = "{}_{}_{}".format(self.coordinator.inverter.name, self.coordinator.inverter.serial, self.sensor_name)

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        if type(self) is SolarmanStatus:
            return True
        return self._attr_available and self.coordinator.inverter.is_connected()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.update()
        self.async_write_ha_state()

    def update(self):
        self._attr_state = self.coordinator.inverter.get_connection_status()
        self._attr_extra_state_attributes["updated"] = self.coordinator.inverter.status_lastUpdate

class SolarmanSensorBase(SolarmanStatus):
    def __init__(self, coordinator, sensor):
        SolarmanStatus.__init__(self, coordinator, sensor)
        self._attr_entity_registry_enabled_default = not "disabled" in sensor

        if "suggested_display_precision" in sensor:
            self._attr_suggested_display_precision = sensor["suggested_display_precision"]

        if "state_class" in sensor and sensor["state_class"]:
            self._attr_extra_state_attributes = { "state_class": sensor["state_class"] }

        self._attr_entity_category = (None)

        self._attr_icon = sensor["icon"] if "icon" in sensor else None

        self.attributes = sensor["attributes"] if "attributes" in sensor else None

    def update(self):
        c = len(self.coordinator.data)
        if c > 1 or (c == 1 and self.sensor_name in self.coordinator.data):
            if self.sensor_name in self.coordinator.data:
                self._attr_state = self.coordinator.data[self.sensor_name]["state"]
                if "value" in self.coordinator.data[self.sensor_name]:
                    self._attr_extra_state_attributes["value"] = self.coordinator.data[self.sensor_name]["value"]
                if self.attributes:
                    for attr in self.attributes:
                        if attr in self.coordinator.data:
                            attr_name = attr.replace(f"{self.sensor_name} ", "")
                            self._attr_extra_state_attributes[attr_name] = self.coordinator.data[attr]["state"]

class SolarmanSensor(SolarmanSensorBase):
    def __init__(self, coordinator, sensor, battery_life_cycle_rating):
        SolarmanSensorBase.__init__(self, coordinator, sensor)

        if "class" in sensor and (device_class := sensor["class"]):
            self._attr_device_class = device_class

        if "device_class" in sensor and (device_class := sensor["device_class"]):
            self._attr_device_class = device_class

        if "uom" in sensor and (unit_of_measurement := sensor["uom"]):
            self._attr_unit_of_measurement = unit_of_measurement

        if "unit_of_measurement" in sensor and (unit_of_measurement := sensor["unit_of_measurement"]):
            self._attr_unit_of_measurement = unit_of_measurement

        if "options" in sensor and (options := sensor["options"]):
            self._attr_options = options
            self._attr_extra_state_attributes = self._attr_extra_state_attributes | { "options": options }

        if "name" in sensor and sensor["name"] == "Battery":
            self._attr_extra_state_attributes = self._attr_extra_state_attributes | { "Life Cycle Rating": battery_life_cycle_rating }