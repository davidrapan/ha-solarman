from __future__ import annotations

from typing import Any
from decimal import Decimal
from logging import getLogger
from datetime import date, datetime, time

from homeassistant.core import callback
from homeassistant.const import EntityCategory, STATE_UNKNOWN, CONF_FRIENDLY_NAME
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.typing import UNDEFINED, StateType, UndefinedType

from .const import *
from .common import *
from .services import *
from .coordinator import Coordinator
from .pysolarman.umodbus.functions import FUNCTION_CODE

_LOGGER = getLogger(__name__)

class SolarmanCoordinatorEntity(CoordinatorEntity[Coordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: Coordinator):
        super().__init__(coordinator)
        self._attr_device_info = self.coordinator.device.info.get(self.coordinator.config_entry.entry_id)
        self._attr_state: StateType = STATE_UNKNOWN
        self._attr_native_value: StateType | str | date | datetime | time | float | Decimal | None = None
        self._attr_extra_state_attributes: dict[str, Any] = {}
        self._attr_value: None = None

    @property
    def device_name(self) -> str:
        return (device_entry.name_by_user or device_entry.name) if (device_entry := self.device_entry) else self.coordinator.device.config.name

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success and self.coordinator.device.state.value > -1

    @callback
    def _handle_coordinator_update(self) -> None:
        self.update()
        self.async_write_ha_state()

    def init(self):
        try:
            self.update()
        except Exception as e:
            _LOGGER.exception(f"{self._attr_name} initialization failed. [{strepr(e)}]")
        return self

    def set_state(self, state, value = None) -> bool:
        self._attr_native_value = self._attr_state = state
        if value is not None:
            self._attr_extra_state_attributes["value"] = self._attr_value = value
        return True

    def update(self):
        if (data := self.coordinator.data.get(self._attr_key)) is not None and self.set_state(*data) and self.attributes:
            if "inverse_sensor" in self.attributes and self._attr_native_value:
                self._attr_extra_state_attributes["−x"] = -self._attr_native_value
            for attr in filter(lambda a: a in self.coordinator.data, self.attributes):
                self._attr_extra_state_attributes[self.attributes[attr].replace(f"{self._attr_name} ", "")] = get_tuple(self.coordinator.data.get(attr))

class SolarmanEntity(SolarmanCoordinatorEntity):
    def __init__(self, coordinator, sensor: dict):
        super().__init__(coordinator)

        self._attr_key = sensor["key"]
        self._attr_name = sensor["name"]
        self._attr_device_class = sensor.get("class") or sensor.get("device_class")
        self._attr_translation_key = sensor.get("translation_key") or slugify(self._attr_name)
        self._attr_unique_id = slugify(self.coordinator.config_entry.entry_id, self._attr_key)
        self._attr_entity_category = sensor.get("category") or sensor.get("entity_category")
        self._attr_entity_registry_enabled_default = not "disabled" in sensor
        self._attr_entity_registry_visible_default = not "hidden" in sensor
        self._attr_friendly_name = sensor.get(CONF_FRIENDLY_NAME)
        self._attr_icon = sensor.get("icon")

        if (unit_of_measurement := sensor.get("uom") or sensor.get("unit_of_measurement")):
            self._attr_native_unit_of_measurement = unit_of_measurement
        if (suggested_unit_of_measurement := sensor.get("suggested_unit_of_measurement")):
            self._attr_suggested_unit_of_measurement = suggested_unit_of_measurement
        if (suggested_display_precision := sensor.get("suggested_display_precision")) is not None:
            self._attr_suggested_display_precision = suggested_display_precision
        if (options := sensor.get("options")):
            self._attr_options = options
            self._attr_extra_state_attributes = self._attr_extra_state_attributes | { "options": options }
        elif "lookup" in sensor and "rule" in sensor and 0 < sensor["rule"] < 5 and (options := [s["value"] for s in sensor["lookup"]]):
            self._attr_device_class = "enum"
            self._attr_options = options
            self._attr_extra_state_attributes = self._attr_extra_state_attributes | { "options": options }
        if alt := sensor.get("alt"):
            self._attr_extra_state_attributes = self._attr_extra_state_attributes | { "Alt Name": alt }
        if description := sensor.get("description"):
            self._attr_extra_state_attributes = self._attr_extra_state_attributes | { "description": description }

        self.attributes = {slugify(x, "sensor"): x for x in attrs} if (attrs := sensor.get("attributes")) is not None else None
        self.registers = sensor.get("registers")

    def _friendly_name_internal(self) -> str | None:
        name = self.name if self.name is not UNDEFINED else None
        if hasattr(self, "platform_data") and self.platform_data and (name_translation_key := self._name_translation_key) and (n := self.platform_data.platform_translations.get(name_translation_key)):
            name = self._substitute_name_placeholders(n)
        elif self._attr_friendly_name:
            name = self._attr_friendly_name
        if not self.has_entity_name or not (device_name := self.device_name):
            return name
        if name is None and self.use_device_name:
            return device_name
        return f"{device_name} {name}"

class SolarmanWritableEntity(SolarmanEntity):
    def __init__(self, coordinator, sensor):
        super().__init__(coordinator, sensor)

        #self._write_lock = "locked" in sensor

        if not "control" in sensor:
            self._attr_entity_category = EntityCategory.CONFIG

        self.code_read = get_code(sensor, "read", FUNCTION_CODE.READ_HOLDING_REGISTERS)
        self.code_write = get_code(sensor, "write", FUNCTION_CODE.WRITE_MULTIPLE_REGISTERS)
        self.register = min(self.registers) if len(self.registers) > 0 else None
        self.maxint = (1 << (16 * len(self.registers))) - 1

        self.writeback = sensor.get("writeback")
        if self.writeback is not None:
            self.writeback_register = self.writeback["register"]
            self.writeback_count = self.writeback["count"]
            self.writeback_overrides = self.writeback.get("overrides") or []

    @property
    def _get_attr_native_value(self):
        if self._attr_native_value is None:
            raise RuntimeError(
                f"{self.name}: Cannot write value when _attr_native_value is None. "
                "This likely means the entity has not received data from the device"
            )
        return self._attr_native_value

    async def write(self, value, state = None) -> None:
        #self.coordinator.device.check(self._write_lock)
        data = value
        register = self.register

        if isinstance(data, int):
            if data < 0:
                data = data + self.maxint + 1
            if data > 0xFFFF:
                data = list(split_p16b(data))[::-1]
            if len(self.registers) > 1 or self.code_write > FUNCTION_CODE.WRITE_SINGLE_REGISTER:
                data = ensure_list(data)
        if isinstance(data, list):
            while len(self.registers) > len(data):
                data.insert(0, 0)
        current_data = await self.coordinator.device.execute(self.code_read, self.register if not self.writeback else self.writeback_register, count = (1 if not isinstance(data, list) else len(data)) if not self.writeback else self.writeback_count)
        if self.writeback and (writeback_data := list(current_data)):
            for override in self.writeback_overrides:
                writeback_data[override["register"] - self.writeback_register] = override["value"]
            if isinstance(data, int):
                writeback_data[self.register - self.writeback_register] = data
            elif isinstance(data, list):
                for idx, val in enumerate(data):
                    writeback_data[self.register + idx - self.writeback_register] = val
            register = self.writeback_register
            data = writeback_data
        if (current_data == (data if self.code_write > FUNCTION_CODE.WRITE_SINGLE_REGISTER else ensure_list(data)) or await self.coordinator.device.execute(self.code_write, register, data = data) > 0) and state is not None:
            self.set_state(state, value)
            self.async_write_ha_state()
            #await self.entity_description.update_fn(self.coordinator., int(value))
            #await self.coordinator.async_request_refresh()
