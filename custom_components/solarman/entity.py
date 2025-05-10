from __future__ import annotations

import logging

from typing import Any
from decimal import Decimal
from datetime import date, datetime, time

from homeassistant.util import slugify
from homeassistant.core import split_entity_id, callback
from homeassistant.const import EntityCategory, STATE_UNKNOWN, CONF_FRIENDLY_NAME
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.entity_registry import RegistryEntry
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.typing import UNDEFINED, StateType, UndefinedType

from .const import *
from .common import *
from .services import *
from .coordinator import Coordinator
from .pysolarman.umodbus.functions import FUNCTION_CODE

_LOGGER = logging.getLogger(__name__)

type SolarmanConfigEntry = ConfigEntry[Coordinator]

@callback
def migrate_unique_ids(config_entry: SolarmanConfigEntry, entity_entry: RegistryEntry) -> dict[str, Any] | None:

    entity_name = entity_entry.original_name if entity_entry.has_entity_name or not entity_entry.original_name else entity_entry.original_name.replace(config_entry.runtime_data.device.config.name, '').strip()

    if entity_entry.unique_id != (unique_id := slugify('_'.join(filter(None, (config_entry.entry_id, entity_name, split_entity_id(entity_entry.entity_id)[0]))))):
        _LOGGER.debug(f"Migrating unique_id for {entity_entry.entity_id} entity from '{entity_entry.unique_id}' to '{unique_id}]'")
        return { "new_unique_id": entity_entry.unique_id.replace(entity_entry.unique_id, unique_id) }

    return None

def create_entity(creator, description):
    try:
        entity = creator(description)

        if description is not None and (nlookup := description.get("name_lookup")) is not None and (prefix := entity.coordinator.data.get(nlookup)) is not None:
            description["name"] = replace_first(description["name"], get_tuple(prefix))
            description["key"] = entity_key(description)
            entity = creator(description)

        entity.update()

        return entity
    except BaseException as e:
        _LOGGER.error(f"Configuring {description} failed. [{format_exception(e)}]")
        raise

class SolarmanCoordinatorEntity(CoordinatorEntity[Coordinator]):
    def __init__(self, coordinator: Coordinator):
        super().__init__(coordinator)
        self._attr_device_info = self.coordinator.device.device_info.get(self.coordinator.device.config.config_entry.entry_id)
        self._attr_state: StateType = STATE_UNKNOWN
        self._attr_native_value: StateType | str | date | datetime | time | float | Decimal = None
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
    def __init__(self, coordinator, sensor):
        super().__init__(coordinator)

        self._attr_key = sensor["key"]
        self._attr_name = sensor["name"]
        self._attr_has_entity_name = True
        self._attr_device_class = sensor.get("class") or sensor.get("device_class")
        self._attr_translation_key = sensor.get("translation_key") or slugify(self._attr_name)
        self._attr_unique_id = slugify('_'.join(filter(None, (self.coordinator.device.config.config_entry.entry_id, self._attr_key))))
        self._attr_entity_category = sensor.get("category") or sensor.get("entity_category")
        self._attr_entity_registry_enabled_default = not "disabled" in sensor
        self._attr_entity_registry_visible_default = not "hidden" in sensor
        self._attr_friendly_name = sensor.get(CONF_FRIENDLY_NAME)
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

        self.attributes = {slugify('_'.join(filter(None, (x, "sensor")))): x for x in attrs} if (attrs := sensor.get("attributes")) is not None else None
        self.registers = sensor.get("registers")

    def _friendly_name_internal(self) -> str | None:
        name = self.name if self.name is not UNDEFINED else None
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

        self.code = get_code(sensor, "write", FUNCTION_CODE.WRITE_MULTIPLE_REGISTERS)
        self.register = min(self.registers) if len(self.registers) > 0 else None
        self.maxint = 0xFFFFFFFF if len(self.registers) > 2 else 0xFFFF

    async def write(self, value, state = None) -> None:
        #self.coordinator.device.check(self._write_lock)
        if isinstance(value, int):
            if value < 0:
                value = value + self.maxint
            if value > 0xFFFF:
                value = list(split_p16b(value))
            if len(self.registers) > 1 or self.code > FUNCTION_CODE.WRITE_SINGLE_REGISTER:
                value = ensure_list(value)
        if isinstance(value, list):
            while len(self.registers) > len(value):
                value.insert(0, 0)
        if await self.coordinator.device.exe(self.code, address = self.register, data = value) > 0 and state is not None:
            self.set_state(state, value)
            self.async_write_ha_state()
            #await self.entity_description.update_fn(self.coordinator., int(value))
            #await self.coordinator.async_request_refresh()
