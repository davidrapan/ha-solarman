from __future__ import annotations

import logging

from typing import Any

from homeassistant.util import slugify
from homeassistant.core import callback
from homeassistant.const import EntityCategory
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.typing import UNDEFINED, StateType, UndefinedType

from .const import *
from .common import *
from .services import *
from .coordinator import InverterCoordinator

_LOGGER = logging.getLogger(__name__)

def create_entity(creator, description):
    try:
        entity = creator(description)

        entity.update()

        return entity
    except BaseException as e:
        _LOGGER.error(f"Configuring {description} failed. [{format_exception(e)}]")
        raise

class SolarmanCoordinatorEntity(CoordinatorEntity[InverterCoordinator]):

    _attr_value: None = None
    _attr_extra_state_attributes: dict[str, Any] = {}

    def __init__(self, coordinator: InverterCoordinator):
        super().__init__(coordinator)
        self._attr_device_info = self.coordinator.inverter.device_info

    @property
    def device_name(self) -> str:
        return (device_entry.name_by_user or device_entry.name) if (device_entry := self.device_entry) else self.coordinator.inverter.name

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success and self.coordinator.inverter.available()

    @callback
    def _handle_coordinator_update(self) -> None:
        self.update()
        self.async_write_ha_state()

    def set_state(self, state, value = None) -> bool:
        self._attr_native_value = self._attr_state = state
        if value is not None:
            self._attr_extra_state_attributes["value"] = self._attr_value = value
        return True

    def update(self):
        if (data := self.coordinator.data.get(self._attr_name)) and self.set_state(*data) and self.attributes:
            if "inverse" in self.attributes and self._attr_native_value:
                self._attr_extra_state_attributes["−x"] = -self._attr_native_value
            for attr in filter(lambda a: a in self.coordinator.data, self.attributes):
                self._attr_extra_state_attributes[attr.replace(f"{self._attr_name} ", "")] = get_tuple(self.coordinator.data.get(attr))

class SolarmanEntity(SolarmanCoordinatorEntity):
    def __init__(self, coordinator, sensor):
        super().__init__(coordinator)

        self._attr_name = sensor["name"]
        self._attr_has_entity_name = True
        self._attr_device_class = sensor.get("class") or sensor.get("device_class")
        self._attr_translation_key = sensor.get("translation_key") or slugify(self._attr_name)
        self._attr_unique_id = '_'.join(filter(None, (self.device_name, str(self.coordinator.inverter.serial), self._attr_name)))
        self._attr_entity_category = sensor.get("category") or sensor.get("entity_category")
        self._attr_entity_registry_enabled_default = not "disabled" in sensor
        self._attr_entity_registry_visible_default = not "hidden" in sensor
        self._attr_friendly_name = sensor.get(ATTR_FRIENDLY_NAME)
        self._attr_icon = sensor.get("icon")

        if (unit_of_measurement := sensor.get("uom") or sensor.get("unit_of_measurement")):
            self._attr_native_unit_of_measurement = unit_of_measurement
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

        self.attributes = sensor.get("attributes")
        self.registers = sensor.get("registers")

    def _friendly_name_internal(self) -> str | None:
        name = self.name
        if self.platform and (name_translation_key := self._name_translation_key) and (n := self.platform.platform_translations.get(name_translation_key)):
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

        self.code = get_code(sensor, "write", CODE.WRITE_MULTIPLE_HOLDING_REGISTERS)
        self.register = min(self.registers) if len(self.registers) > 0 else None

    async def write(self, value, state = None) -> None:
        #self.coordinator.inverter.check(self._write_lock)
        if isinstance(value, int):
            if value > 0xFFFF:
                value = list(split_p16b(value))
            if len(self.registers) > 1:
                value = ensure_list(value)
        if isinstance(value, list):
            while len(self.registers) > len(value):
                value.insert(0, 0)
        if await self.coordinator.inverter.call(self.code, self.register, value, ACTION_ATTEMPTS_MAX) > 0 and state:
            self.set_state(state, value)
            self.async_write_ha_state()
            #await self.entity_description.update_fn(self.coordinator., int(value))
            #await self.coordinator.async_request_refresh()