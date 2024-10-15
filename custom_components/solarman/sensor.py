from __future__ import annotations

import logging

from typing import Any

from homeassistant.components.template.sensor import SensorTemplate
from homeassistant.components.template.sensor import TriggerSensorEntity
from homeassistant.helpers.template import Template

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.components.sensor import RestoreSensor, SensorEntity, SensorDeviceClass
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import *
from .common import *
from .services import *
from .entity import create_entity, SolarmanEntity

_LOGGER = logging.getLogger(__name__)

_PLATFORM = get_current_file_name(__name__)

def _create_entity(coordinator, description, options):
    if "artificial" in description:
        match description["artificial"]:
            case "interval":
                return SolarmanIntervalSensor(coordinator, description)
    elif (name := description["name"]) and "Battery" in name:
        battery_nominal_voltage = options.get(CONF_BATTERY_NOMINAL_VOLTAGE, 0)
        battery_life_cycle_rating = options.get(CONF_BATTERY_LIFE_CYCLE_RATING, 0)
        if "registers" in description:
            if name == "Battery":
                return SolarmanBatterySensor(coordinator, description, battery_nominal_voltage, battery_life_cycle_rating)
        else:
            if name == "Battery State":
                return SolarmanBatteryCustomSensor(coordinator, description, battery_nominal_voltage, battery_life_cycle_rating)
            elif battery_nominal_voltage > 0 and battery_life_cycle_rating > 0 and name in ("Battery SOH", "Today Battery Life Cycles", "Total Battery Life Cycles"):
                return SolarmanBatteryCustomSensor(coordinator, description, battery_nominal_voltage, battery_life_cycle_rating)

    if "restore" in description or "ensure_increasing" in description:
        return SolarmanRestoreSensor(coordinator, description)

    return SolarmanSensor(coordinator, description)

async def async_setup_entry(hass: HomeAssistant, config: ConfigEntry, async_add_entities: AddEntitiesCallback) -> bool:
    _LOGGER.debug(f"async_setup_entry: {config.options}")
    coordinator = hass.data[DOMAIN][config.entry_id]

    descriptions = coordinator.inverter.get_entity_descriptions()

    _LOGGER.debug(f"async_setup: async_add_entities")

    async_add_entities(create_entity(lambda x: _create_entity(coordinator, x, config.options), d) for d in descriptions if (is_platform(d, _PLATFORM) and not "configurable" in d))

    return True

async def async_unload_entry(hass: HomeAssistant, config: ConfigEntry) -> bool:
    _LOGGER.debug(f"async_unload_entry: {config.options}")

    return True

class SolarmanSensorEntity(SolarmanEntity, SensorEntity):
    def __init__(self, coordinator, platform, sensor):
        super().__init__(coordinator, platform, sensor)
        if "state_class" in sensor and (state_class := sensor["state_class"]):
            self._attr_state_class = state_class

class SolarmanIntervalSensor(SolarmanSensorEntity):
    def __init__(self, coordinator, sensor):
        super().__init__(coordinator, _PLATFORM, sensor)
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_native_unit_of_measurement = "s"
        self._attr_state_class = "duration"
        self._attr_icon = "mdi:update"

    @property
    def available(self) -> bool:
        return self._attr_native_value > 0

    def update(self):
        self.set_state(self.coordinator.inverter.state_interval.total_seconds())

class SolarmanSensor(SolarmanSensorEntity):
    def __init__(self, coordinator, sensor):
        super().__init__(coordinator, _PLATFORM, sensor)
        self._sensor_ensure_increasing = "ensure_increasing" in sensor

class SolarmanRestoreSensor(SolarmanSensor, RestoreSensor):
    async def async_added_to_hass(self) -> None:
        """Handle entity which will be added."""
        await super().async_added_to_hass()

        if (last_sensor_data := await self.async_get_last_sensor_data()) is not None:
            self._attr_native_value = last_sensor_data.native_value
            self._attr_native_unit_of_measurement = last_sensor_data.native_unit_of_measurement

    def set_state(self, state):
        if self._sensor_ensure_increasing and self._attr_native_value and self._attr_native_value > state > 0:
            return

        self._attr_state = self._attr_native_value = state

class SolarmanBatterySensor(SolarmanSensor):
    def __init__(self, coordinator, sensor, battery_nominal_voltage, battery_life_cycle_rating):
        super().__init__(coordinator, sensor)
        if battery_nominal_voltage > 0 and battery_life_cycle_rating > 0:
            self._attr_extra_state_attributes = self._attr_extra_state_attributes | { "Nominal Voltage": battery_nominal_voltage, "Life Cycle Rating": battery_life_cycle_rating }

class SolarmanBatteryCustomSensor(SolarmanSensor):
    def __init__(self, coordinator, sensor, battery_nominal_voltage, battery_life_cycle_rating):
        super().__init__(coordinator, sensor)
        self._battery_nominal_voltage = battery_nominal_voltage
        self._battery_life_cycle_rating = battery_life_cycle_rating
        self._digits = sensor["digits"] if "digits" in sensor else DEFAULT_DIGITS

    def update(self):
        #super().update()
        c = len(self.coordinator.data)
        if c > 1 or (c == 1 and self.sensor_name in self.coordinator.data):
            match self.sensor_name:
                case "Battery SOH":
                    total_battery_charge = self.get_data("Total Battery Charge", None)
                    if total_battery_charge == 0:
                        self.set_state(100)
                        return
                    battery_capacity = self.get_data("Battery Capacity", None)
                    battery_corrected_capacity = self.get_data("Battery Corrected Capacity", None)
                    if battery_capacity and battery_corrected_capacity:
                        battery_capacity_5 = battery_capacity / 100 * 5
                        if battery_capacity - battery_capacity_5 <= battery_corrected_capacity <= battery_capacity + battery_capacity_5:
                            battery_capacity = battery_corrected_capacity
                    if total_battery_charge and battery_capacity and self._battery_nominal_voltage and self._battery_life_cycle_rating:
                        self.set_state(get_number(100 - total_battery_charge / get_battery_power_capacity(battery_capacity, self._battery_nominal_voltage) / (self._battery_life_cycle_rating * 0.05), self._digits))
                case "Battery State":
                    battery_power = self.get_data("Battery Power", None)
                    if battery_power:
                        self.set_state("discharging" if battery_power > 50 else "charging" if battery_power < -50 else "idle")
                case "Today Battery Life Cycles":
                    today_battery_charge = self.get_data("Today Battery Charge", None)
                    if today_battery_charge == 0:
                        self.set_state(0)
                        return
                    battery_capacity = self.get_data("Battery Capacity", None)
                    battery_corrected_capacity = self.get_data("Battery Corrected Capacity", None)
                    if battery_capacity and battery_corrected_capacity:
                        battery_capacity_5 = battery_capacity / 100 * 5
                        if battery_capacity - battery_capacity_5 <= battery_corrected_capacity <= battery_capacity + battery_capacity_5:
                            battery_capacity = battery_corrected_capacity
                    if today_battery_charge and battery_capacity and self._battery_nominal_voltage:
                        self.set_state(get_number(get_battery_cycles(today_battery_charge, battery_capacity, self._battery_nominal_voltage), self._digits))
                case "Total Battery Life Cycles":
                    total_battery_charge = self.get_data("Total Battery Charge", None)
                    if total_battery_charge == 0:
                        self.set_state(0)
                        return
                    battery_capacity = self.get_data("Battery Capacity", None)
                    battery_corrected_capacity = self.get_data("Battery Corrected Capacity", None)
                    if battery_capacity and battery_corrected_capacity:
                        battery_capacity_5 = battery_capacity / 100 * 5
                        if battery_capacity - battery_capacity_5 <= battery_corrected_capacity <= battery_capacity + battery_capacity_5:
                            battery_capacity = battery_corrected_capacity
                    if total_battery_charge and battery_capacity and self._battery_nominal_voltage:
                        self.set_state(get_number(get_battery_cycles(total_battery_charge, battery_capacity, self._battery_nominal_voltage), self._digits))
