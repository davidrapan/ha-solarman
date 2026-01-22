from __future__ import annotations

from typing import Any
from logging import getLogger

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, STATE_OFF, STATE_ON
from homeassistant.components.switch import SwitchEntity, SwitchDeviceClass, SwitchEntityDescription
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import *
from .common import *
from .services import *
from .entity import SolarmanEntity, SolarmanWritableEntity, Coordinator

_LOGGER = getLogger(__name__)

_PLATFORM = get_current_file_name(__name__)

async def async_setup_entry(_: HomeAssistant, config_entry: ConfigEntry[Coordinator], async_add_entities: AddEntitiesCallback) -> bool:
    _LOGGER.debug(f"async_setup_entry: {config_entry.options}")

    async_add_entities([SolarmanAccessPoint(config_entry.runtime_data)] + [SolarmanSwitchEntity(config_entry.runtime_data, d).init() for d in config_entry.runtime_data.device.profile.parser.get_entity_descriptions(_PLATFORM)])

    return True

async def async_unload_entry(_: HomeAssistant, config_entry: ConfigEntry[Coordinator]) -> bool:
    _LOGGER.debug(f"async_unload_entry: {config_entry.options}")

    return True

class SolarmanAccessPoint(SolarmanEntity, SwitchEntity):
    def __init__(self, coordinator):
        SolarmanEntity.__init__(self, coordinator, {"key": "access_point_switch", "name": "Access Point"})
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_device_class = SwitchDeviceClass.SWITCH
        self._attr_icon = "mdi:access-point"

    @property
    def available(self):
        return self.coordinator.device.endpoint.info is not None and self.is_on is not None

    @property
    def is_on(self):
        for i in LOGGER_REGEX["ap"].finditer(self.coordinator.device.endpoint.info):
            match i.group(1):
                case "0":
                    return True
                case "1":
                    return False
        return None

    async def async_turn_(self, mode: int):
        await self.coordinator.device.endpoint.load()
        if self.is_on is False:
            await request(self.coordinator.device.config.host, LOGGER_CMD, LOGGER_SET, {"apsta_mode": mode, "mode_sel": mode})
            await self.coordinator.device.endpoint.load()
            await request(self.coordinator.device.config.host, LOGGER_SUCCESS, LOGGER_CMD, LOGGER_RESTART_DATA)
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs: Any):
        await self.async_turn_(0)

    async def async_turn_off(self, **kwargs: Any):
        await self.async_turn_(1)

class SolarmanSwitchEntity(SolarmanWritableEntity, SwitchEntity):
    def __init__(self, coordinator, sensor):
        SolarmanWritableEntity.__init__(self, coordinator, sensor)
        self._attr_device_class = SwitchDeviceClass.SWITCH

        self._value_on = 1
        self._value_off = 0
        self._value_bit = None
        if "value" in sensor and (value := sensor["value"]) and not isinstance(value, int):
            if True in value:
                self._value_on = value[True]
            if "on" in value:
                self._value_on = value["on"]
            if False in value:
                self._value_off = value[False]
            if "off" in value:
                self._value_off = value["off"]
            if "bit" in value:
                self._value_bit = value["bit"]

    def _to_native_value(self, value: int) -> int:
        if self._value_bit is not None:
            return (self._get_attr_native_value & ~(1 << self._value_bit)) | (value << self._value_bit)
        return value

    @property
    def is_on(self) -> bool | None:
        return (
            self._attr_native_value >> self._value_bit & 1
            if self._attr_native_value is not None and self._value_bit is not None
            else self._attr_native_value
        ) != self._value_off

    async def async_turn_on(self, **kwargs: Any):
        value = self._to_native_value(self._value_on)
        await self.write(value, value)

    async def async_turn_off(self, **kwargs: Any):
        value = self._to_native_value(self._value_off)
        await self.write(value, value)
