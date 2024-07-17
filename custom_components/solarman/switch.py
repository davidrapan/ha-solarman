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

from .const import *
from .common import *
from .services import *
from .api import Inverter
from .coordinator import InverterCoordinator
from .entity import SolarmanCoordinatorEntity, SolarmanBaseEntity, SolarmanEntity
from .sensor import SolarmanSensor

_LOGGER = logging.getLogger(__name__)

def _create_sensor(coordinator, sensor, battery_nominal_voltage, battery_life_cycle_rating):
    try:
        entity = SolarmanSwitchSensor(coordinator, sensor, battery_life_cycle_rating)

        entity.update()

        return entity
    except BaseException as e:
        _LOGGER.error(f"Configuring {sensor} failed. [{format_exception(e)}]")
        raise

async def async_setup_entry(hass: HomeAssistant, config: ConfigEntry, async_add_entities: AddEntitiesCallback) -> bool:
    _LOGGER.debug(f"async_setup_entry: {config.options}")
    coordinator = hass.data[DOMAIN][config.entry_id]

    options = config.options

    battery_nominal_voltage = options.get(CONF_BATTERY_NOMINAL_VOLTAGE)
    battery_life_cycle_rating = options.get(CONF_BATTERY_LIFE_CYCLE_RATING)

    sensors = coordinator.inverter.get_sensors()

    # Add entities.
    #
    _LOGGER.debug(f"async_setup: async_add_entities")

    async_add_entities(_create_sensor(coordinator, sensor, battery_nominal_voltage, battery_life_cycle_rating) for sensor in sensors if "switch" in sensor)
    return True

async def async_unload_entry(hass: HomeAssistant, config: ConfigEntry) -> bool:
    _LOGGER.debug(f"async_unload_entry: {config.options}")
    return True

class SolarmanSwitchSensor(SolarmanSensor, SwitchEntity):
    def __init__(self, coordinator, sensor, battery_life_cycle_rating):
        SolarmanSensor.__init__(self, coordinator, sensor, battery_life_cycle_rating)

        # Set the category of the sensor.
        self._attr_entity_category = (EntityCategory.CONFIG)

        self._attr_device_class = "switch"

        registers = sensor["registers"]
        registers_length = len(registers)

        if registers_length > 0:
            self.register = sensor["registers"][0]

        if registers_length > 1:
            _LOGGER.warning(f"SolarmanSwitchSensor.__init__: Contains more than 1 register!")

    @property
    def is_on(self) -> bool | None:
        """Return True if entity is on."""
        return self._attr_state != 0

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the entity on."""
        await self.coordinator.inverter.service_write_multiple_holding_registers(self.register, [65280,])
        self._attr_state = 1
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the entity off."""
        await self.coordinator.inverter.service_write_multiple_holding_registers(self.register, [0,])
        self._attr_state = 0
        self.async_write_ha_state()
