from __future__ import annotations

from logging import getLogger

from homeassistant.core import HomeAssistant
from homeassistant.const import MAJOR_VERSION, MINOR_VERSION, EntityCategory
from homeassistant.config_entries import ConfigEntry
from homeassistant.components.sensor import RestoreSensor, SensorEntity
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import *
from .common import *
from .services import *
from .entity import SolarmanEntity, Coordinator

_LOGGER = getLogger(__name__)

_PLATFORM = get_current_file_name(__name__)

def _create_entity(coordinator, description, options):
    if (name := description["name"]) and "Battery" in name and (additional := options.get(CONF_ADDITIONAL_OPTIONS, {})) is not None:
        battery_nominal_voltage = additional.get(CONF_BATTERY_NOMINAL_VOLTAGE, DEFAULT_[CONF_BATTERY_NOMINAL_VOLTAGE])
        battery_life_cycle_rating = additional.get(CONF_BATTERY_LIFE_CYCLE_RATING, DEFAULT_[CONF_BATTERY_LIFE_CYCLE_RATING])
        if "registers" in description:
            if name == "Battery":
                return SolarmanBatterySensor(coordinator, description, battery_nominal_voltage, battery_life_cycle_rating)
        else:
            if name == "Battery State":
                return SolarmanBatteryCustomSensor(coordinator, description, battery_nominal_voltage, battery_life_cycle_rating)
            elif battery_nominal_voltage > 0 and battery_life_cycle_rating > 0 and name in ("Battery SOH", "Today Battery Life Cycles", "Total Battery Life Cycles"):
                return SolarmanBatteryCustomSensor(coordinator, description, battery_nominal_voltage, battery_life_cycle_rating)
            elif name == "Battery Capacity":
                return SolarmanBatteryCapacitySensor(coordinator, description)

    if "persistent" in description:
        return SolarmanPersistentSensor(coordinator, description)

    if "restore" in description or "ensure_increasing" in description:
        return SolarmanRestoreSensor(coordinator, description)

    if "via_device" in description:
        return SolarmanNestedSensor(coordinator, description)

    return SolarmanSensor(coordinator, description)

async def async_setup_entry(_: HomeAssistant, config_entry: ConfigEntry[Coordinator], async_add_entities: AddEntitiesCallback) -> bool:
    _LOGGER.debug(f"async_setup_entry: {config_entry.options}")

    async_add_entities([SolarmanIntervalSensor(config_entry.runtime_data)] + [_create_entity(config_entry.runtime_data, d, config_entry.options).init() for d in config_entry.runtime_data.device.profile.parser.get_entity_descriptions(_PLATFORM)])

    return True

async def async_unload_entry(_: HomeAssistant, config_entry: ConfigEntry[Coordinator]) -> bool:
    _LOGGER.debug(f"async_unload_entry: {config_entry.options}")

    return True

class SolarmanSensorEntity(SolarmanEntity, SensorEntity):
    def __init__(self, coordinator, sensor):
        super().__init__(coordinator, sensor)
        if "state_class" in sensor and (state_class := sensor["state_class"]):
            self._attr_state_class = state_class

class SolarmanIntervalSensor(SolarmanSensorEntity):
    def __init__(self, coordinator):
        super().__init__(coordinator, {"key": "update_interval_sensor", "name": "Update Interval"})
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_native_unit_of_measurement = "s"
        self._attr_state_class = "measurement"
        self._attr_device_class = "duration"
        self._attr_icon = "mdi:update"
        self._attr_native_value = 0

    @property
    def available(self) -> bool:
        return self._attr_native_value is not None

    def update(self):
        self.set_state(self.coordinator.device.state.updated_interval.total_seconds())

class SolarmanSensor(SolarmanSensorEntity):
    def __init__(self, coordinator, sensor):
        super().__init__(coordinator, sensor)
        self._sensor_ensure_increasing = "ensure_increasing" in sensor

class SolarmanNestedSensor(SolarmanSensorEntity):
    def __init__(self, coordinator, sensor):
        super().__init__(coordinator, sensor)
        parent_device_info = self.coordinator.device.info.get(self.coordinator.config_entry.entry_id)
        device_serial_number, _ = self.coordinator.data[slugify(sensor["group"], "serial", "number", "sensor")]
        if not device_serial_number in self.coordinator.device.info:
            self.coordinator.device.info[device_serial_number] = build_device_info(None, str(device_serial_number), None, None, None, parent_device_info["name"])
            if (MAJOR_VERSION, MINOR_VERSION) >= (2026, 8):
                # via_device is deprecated since HA 2026.8 (removed in 2027.8), link the parent by its device registry id instead
                self.coordinator.device.info[device_serial_number]["via_device_id"] = dr.async_get(self.coordinator.hass).async_get_or_create(config_entry_id = self.coordinator.config_entry.entry_id, **parent_device_info).id
            else:
                self.coordinator.device.info[device_serial_number]["via_device"] = (DOMAIN, parent_device_info.get("serial_number", self.coordinator.config_entry.entry_id))
            self.coordinator.device.info[device_serial_number]["manufacturer"] = parent_device_info["manufacturer"]
            self.coordinator.device.info[device_serial_number]["model"] = None
        self._attr_device_info = self.coordinator.device.info[device_serial_number]
        self._attr_name.replace(f"{sensor["group"]} ", '')

class SolarmanRestoreSensor(SolarmanSensor, RestoreSensor):
    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if last_sensor_data := await self.async_get_last_sensor_data():
            self._attr_native_value = last_sensor_data.native_value

    def set_state(self, state, value = None) -> bool:
        if self._sensor_ensure_increasing and self._attr_native_value is not None and state is not None and self._attr_native_value > state > 0:
            return False
        return super().set_state(state, value)

class SolarmanPersistentSensor(SolarmanRestoreSensor):
    @property
    def available(self) -> bool:
        return True

class SolarmanBatterySensor(SolarmanSensor):
    def __init__(self, coordinator, sensor, battery_nominal_voltage, battery_life_cycle_rating):
        super().__init__(coordinator, sensor)
        if battery_nominal_voltage > 0 and battery_life_cycle_rating > 0:
            self._attr_extra_state_attributes = self._attr_extra_state_attributes | { "Nominal Voltage": battery_nominal_voltage, "Life Cycle Rating": battery_life_cycle_rating }

class SolarmanBatteryCapacitySensor(SolarmanRestoreSensor):
    # Up to 1000 samples each, together close to the recorder's 16 KB attribute limit. They are restored on startup
    # from the restore state, so the recorder doesn't need them.
    _unrecorded_attributes = frozenset({"samples", "states"})

    def __init__(self, coordinator, sensor):
        super().__init__(coordinator, sensor)
        self._digits = sensor.get(DIGITS, DEFAULT_[DIGITS])
        self._threshold = sensor.get("threshold", 200)
        self._nstates = sensor.get("states", 1000)
        self._window = sensor.get("window", 1)
        self._states = []
        self._samples = []
        self._start = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if state := await self.async_get_last_state():
            if "states" in state.attributes:
                self._attr_extra_state_attributes["states"] = self._states = state.attributes["states"]
            if "samples" in state.attributes:
                self._attr_extra_state_attributes["samples"] = self._samples = state.attributes["samples"]

    def update(self):
        # Capacity = total energy / total SOC change over windows of a fixed amount of energy (#1218).
        # The counter (0.1 kWh) and SOC (1 %) are coarse, so a single window is noisy, but the rounding cancels out in
        # the sums. A window ends on the energy counter only, never on SOC, and windows with no SOC change are kept:
        # choosing windows by their SOC change would bias the result just like averaging the per-window ratios did.
        if (power := get_tuple(self.coordinator.data.get("battery_power_sensor"))) is None:
            return
        is_charging = power < 0
        if abs(power) < self._threshold or (self._start is not None and self._start[0] != is_charging):
            self._start = None
            return
        if (soc := get_tuple(self.coordinator.data.get("battery_sensor"))) is None or (tb := get_tuple(self.coordinator.data.get("total_battery_charge_sensor" if is_charging else "total_battery_discharge_sensor"))) is None:
            return
        if self._start is None or (energy := tb - self._start[2]) < 0:
            self._start = (is_charging, soc, tb)
            return
        if energy < self._window:
            return
        diff = abs(soc - self._start[1])
        self._start = (is_charging, soc, tb)
        self._samples.append([round(energy, 3), diff])
        if diff > 0:
            self._states.append(get_number(energy * 100 / diff, self._digits))
        while len(self._samples) > self._nstates:
            self._samples.pop(0)
        while len(self._states) > self._nstates:
            self._states.pop(0)
        self._attr_extra_state_attributes["samples"] = self._samples
        self._attr_extra_state_attributes["states"] = self._states
        if len(self._samples) > 10 and (soc_sum := sum(x[1] for x in self._samples)) > 0:
            self.set_state(get_number(sum(x[0] for x in self._samples) * 100 / soc_sum, self._digits))

class SolarmanBatteryCustomSensor(SolarmanSensor):
    def __init__(self, coordinator, sensor, battery_nominal_voltage, battery_life_cycle_rating):
        super().__init__(coordinator, sensor)
        self._digits = sensor.get(DIGITS, DEFAULT_[DIGITS])
        self._battery_nominal_voltage = battery_nominal_voltage
        self._battery_life_cycle_rating = battery_life_cycle_rating

    def update(self):
        #super().update()
        c = len(self.coordinator.data)
        if c > 1 or (c == 1 and self._attr_key in self.coordinator.data):
            match self._attr_key:
                case "battery_soh_sensor":
                    total_battery_charge = get_tuple(self.coordinator.data.get("total_battery_charge_sensor"))
                    if total_battery_charge == 0:
                        self.set_state(100)
                        return
                    battery_capacity = get_tuple(self.coordinator.data.get("battery_capacity_number"))
                    battery_corrected_capacity = get_tuple(self.coordinator.data.get("battery_corrected_capacity_sensor"))
                    if battery_capacity and battery_corrected_capacity:
                        battery_capacity_5 = battery_capacity / 100 * 5
                        if battery_capacity - battery_capacity_5 <= battery_corrected_capacity <= battery_capacity + battery_capacity_5:
                            battery_capacity = battery_corrected_capacity
                    if total_battery_charge and battery_capacity and self._battery_nominal_voltage and self._battery_life_cycle_rating:
                        self.set_state(get_number(100 - total_battery_charge / get_battery_power_capacity(battery_capacity, self._battery_nominal_voltage) / (self._battery_life_cycle_rating * 0.05), self._digits))
                case "battery_state_sensor":
                    battery_power = get_tuple(self.coordinator.data.get("battery_power_sensor"))
                    if battery_power:
                        self.set_state("discharging" if battery_power > 50 else "charging" if battery_power < -50 else "idle")
                case "today_battery_life_cycles_sensor":
                    today_battery_charge = get_tuple(self.coordinator.data.get("today_battery_charge_sensor"))
                    if today_battery_charge == 0:
                        self.set_state(0)
                        return
                    battery_capacity = get_tuple(self.coordinator.data.get("battery_capacity_number"))
                    battery_corrected_capacity = get_tuple(self.coordinator.data.get("battery_corrected_capacity_sensor"))
                    if battery_capacity and battery_corrected_capacity:
                        battery_capacity_5 = battery_capacity / 100 * 5
                        if battery_capacity - battery_capacity_5 <= battery_corrected_capacity <= battery_capacity + battery_capacity_5:
                            battery_capacity = battery_corrected_capacity
                    if today_battery_charge and battery_capacity and self._battery_nominal_voltage:
                        self.set_state(get_number(get_battery_cycles(today_battery_charge, battery_capacity, self._battery_nominal_voltage), self._digits))
                case "total_battery_life_cycles_sensor":
                    total_battery_charge = get_tuple(self.coordinator.data.get("total_battery_charge_sensor"))
                    if total_battery_charge == 0:
                        self.set_state(0)
                        return
                    battery_capacity = get_tuple(self.coordinator.data.get("battery_capacity_number"))
                    battery_corrected_capacity = get_tuple(self.coordinator.data.get("battery_corrected_capacity_sensor"))
                    if battery_capacity and battery_corrected_capacity:
                        battery_capacity_5 = battery_capacity / 100 * 5
                        if battery_capacity - battery_capacity_5 <= battery_corrected_capacity <= battery_capacity + battery_capacity_5:
                            battery_capacity = battery_corrected_capacity
                    if total_battery_charge and battery_capacity and self._battery_nominal_voltage:
                        self.set_state(get_number(get_battery_cycles(total_battery_charge, battery_capacity, self._battery_nominal_voltage), self._digits))
