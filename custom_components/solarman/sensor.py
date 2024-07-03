from __future__ import annotations

import re
import string
import logging
import asyncio
import aiofiles
import voluptuous as vol

from homeassistant.core import HomeAssistant, callback
from homeassistant.const import CONF_NAME, EntityCategory
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo, format_mac
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import *
from .common import *
from .discovery import InverterDiscovery
from .coordinator import InverterCoordinator
from .api import Inverter
from .services import *

_LOGGER = logging.getLogger(__name__)

_FMT = string.Formatter()

def _create_sensor(coordinator, inverter_name, inverter, sensor, config, disable_templating):
    try:
        if "artificial" in sensor:
            entity = SolarmanStatus(coordinator, inverter_name, inverter, sensor["name"])
        elif "isstr" in sensor:
            entity = SolarmanSensorText(coordinator, inverter_name, inverter, sensor, config, disable_templating)
        else:
            entity = SolarmanSensor(coordinator, inverter_name, inverter, sensor, config, disable_templating)

        entity.update()

        return entity
    except BaseException as e:
        _LOGGER.error(f"Configuring {sensor} failed. [{format_exception(e)}]")
        raise

async def async_setup(hass: HomeAssistant, config, async_add_entities: AddEntitiesCallback, id = None):
    _LOGGER.debug(f"async_setup: {config}")

    lookup_path = hass.config.path(LOOKUP_DIRECTORY_PATH)

    inverter_name = config.get(CONF_NAME)
    inverter_discovery = config.get(CONF_INVERTER_DISCOVERY)
    inverter_host = config.get(CONF_INVERTER_HOST)
    inverter_serial = config.get(CONF_INVERTER_SERIAL)
    inverter_port = config.get(CONF_INVERTER_PORT)
    inverter_mb_slave_id = config.get(CONF_INVERTER_MB_SLAVE_ID)
    lookup_file = config.get(CONF_LOOKUP_FILE)
    battery_nominal_voltage = config.get(CONF_BATTERY_NOMINAL_VOLTAGE)
    battery_life_cycle_rating = config.get(CONF_BATTERY_LIFE_CYCLE_RATING)
    disable_templating = config.get(CONF_DISABLE_TEMPLATING)

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

    if not battery_nominal_voltage:
        battery_nominal_voltage = DEFAULT_BATTERY_NOMINAL_VOLTAGE

    if not battery_life_cycle_rating:
        battery_life_cycle_rating = DEFAULT_BATTERY_LIFE_CYCLE_RATING

    if not disable_templating:
        disable_templating = DEFAULT_DISABLE_TEMPLATING

    if inverter_host is None:
        raise vol.Invalid("configuration parameter [inverter_host] does not have a value")
    if inverter_serial is None:
        raise vol.Invalid("configuration parameter [inverter_serial] does not have a value")

    inverter = Inverter(inverter_host, inverter_mac, inverter_serial, inverter_port, inverter_mb_slave_id, lookup_path, lookup_file)
    sensors = await inverter.get_sensors()
    coordinator = InverterCoordinator(hass, inverter)

    hass.data.setdefault(DOMAIN, {})[id] = coordinator

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

    _LOGGER.debug(f"async_setup: async_add_entities")
    async_add_entities(_create_sensor(coordinator, inverter_name, inverter, sensor, { "Battery Nominal Voltage": battery_nominal_voltage, "Battery Life Cycle Rating": battery_life_cycle_rating }, disable_templating) for sensor in sensors)

    _LOGGER.debug(f"async_setup: register_services")
    register_services(hass, inverter)

# Set-up from configuration.yaml
#async def async_setup_platform(hass: HomeAssistant, config, async_add_entities: AddEntitiesCallback, discovery_info = None):
#    _LOGGER.debug(f"async_setup_platform: {config}") 
#    await async_setup(hass, config, async_add_entities)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> bool:
    _LOGGER.debug(f"async_setup_entry: {entry.options}") 
    await async_setup(hass, entry.options, async_add_entities, entry.entry_id)
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    _LOGGER.debug(f"async_unload_entry: remove_services {entry.options}") 
    remove_services(hass)
    return True

class InverterCoordinatorEntity(CoordinatorEntity[InverterCoordinator]):
    def __init__(self, coordinator: InverterCoordinator, id: str = None, device_name: str = None, device_lookup_file: str = None, manufacturer: str = None):
        super().__init__(coordinator)
        self.id = coordinator.inverter.serial
        self.device_name = device_name
        self.model = device_lookup_file.replace(".yaml", "")
        
        if '_' in self.model:
            dev_man = self.model.split('_')
            self.model = dev_man[1].upper()
            self.manufacturer = dev_man[0].capitalize()

        self._attr_device_info = {
            "connections": {(CONNECTION_NETWORK_MAC, format_mac(self.coordinator.inverter.mac))}
            } if self.coordinator.inverter.mac else {}

        self._attr_device_info = self._attr_device_info | {
            "identifiers": {(DOMAIN, self.id)},
            "name": self.device_name,
            "model": self.model,
            "manufacturer": self.manufacturer
        }

        self._attr_extra_state_attributes = { "id": self.id, "integration": DOMAIN }

class SolarmanStatus(InverterCoordinatorEntity):
    def __init__(self, coordinator, inverter_name, inverter, field_name):
        super().__init__(coordinator, inverter.serial, inverter_name, inverter.lookup_file)
        self._inverter_name = inverter_name
        self._field_name = field_name

        #  Return the category of the sensor.
        self._attr_entity_category = (EntityCategory.DIAGNOSTIC)

        #  Return the icon of the sensor.
        self._attr_icon = "mdi:information"

        #  Return the name of the sensor.
        self._attr_name = "{} {}".format(self._inverter_name, self._field_name)

        #  Return a unique_id based on the serial number
        self._attr_unique_id = "{}_{}_{}".format(self._inverter_name, self.coordinator.inverter.serial, self._field_name)

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

class SolarmanSensorText(SolarmanStatus):
    def __init__(self, coordinator, inverter_name, inverter, sensor, config, disable_templating):
        SolarmanStatus.__init__(self, coordinator, inverter_name, inverter, sensor["name"])
        self._attr_entity_registry_enabled_default = not "disabled" in sensor

        if "display_precision" in sensor:
            self._attr_suggested_display_precision = sensor["display_precision"]

        if "display_precision" in sensor:
            self._suggested_display_precision = sensor["display_precision"]

        if "state_class" in sensor and sensor["state_class"]:
            self._attr_extra_state_attributes = { "state_class": sensor["state_class"] }

        self._attr_entity_category = (None)

        self._attr_icon = sensor["icon"] if "icon" in sensor else None

        self.attributes = sensor["attributes"] if "attributes" in sensor else None

        self.config = config

        self.is_ok = True

        self.params = sensor["params"] if "params" in sensor else None

        self.formula = sensor["formula"] if "formula" in sensor else None

        if not disable_templating:
            if self.params and self.formula:
                self.formula_pcount = len([p for p in _FMT.parse(self.formula) if p[2] is not None])
                if self.formula_pcount != len(self.params):
                    self.is_ok = False
                    _LOGGER.error(f"{self._field_name} template is not valid.")
        elif "formula" in sensor:
            self.is_ok = False

    def _lookup_param(self, p):
        if p in self.coordinator.data:
            return self.coordinator.data[p]

        if p in self.config:
            return self.config[p]

        return 0

    def update(self):
        if not self.is_ok:
            return

        c = len(self.coordinator.data)
        if c > 1 or (c == 1 and self._field_name in self.coordinator.data):
            if self._field_name in self.coordinator.data:
                self._attr_state = self.coordinator.data[self._field_name]
                if self.attributes:
                    for attr in self.attributes:
                        if attr in self.coordinator.data:
                            attr_name = attr.replace(f"{self._field_name} ", "")
                            self._attr_extra_state_attributes[attr_name] = self.coordinator.data[attr]
                if self._field_name + " enum" in self.coordinator.data:
                    self._attr_extra_state_attributes["Value"] = self.coordinator.data[self._field_name + " enum"]
            elif self.formula:
                if set(self.params) <= self.coordinator.data.keys() | self.config:
                    params = [self._lookup_param(p) for p in self.params]
                    if self.formula_pcount == len(params):
                        formula = self.formula.format(*params)
                        self._attr_state = eval(formula)

class SolarmanSensor(SolarmanSensorText):
    def __init__(self, coordinator, inverter_name, inverter, sensor, config, disable_templating):
        SolarmanSensorText.__init__(self, coordinator, inverter_name, inverter, sensor, config, disable_templating)

        if device_class := sensor["class"]:
            self._attr_device_class = device_class

        if unit_of_measurement := sensor["uom"]:
            self._attr_unit_of_measurement = unit_of_measurement

        if sensor["name"] == "Battery":
            self._attr_extra_state_attributes = self._attr_extra_state_attributes | { "Nominal Voltage": config["Battery Nominal Voltage"], "Life Cycle Rating": config["Battery Life Cycle Rating"] }