from __future__ import annotations

import logging

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.const import STATE_OFF, STATE_ON, EntityCategory
from homeassistant.components.switch import SwitchEntity, SwitchDeviceClass, SwitchEntityDescription
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import *
from .common import *
from .services import *
from .entity import create_entity, SolarmanEntity

_LOGGER = logging.getLogger(__name__)

_PLATFORM = get_current_file_name(__name__)

async def async_setup_entry(hass: HomeAssistant, config: ConfigEntry, async_add_entities: AddEntitiesCallback) -> bool:
    _LOGGER.debug(f"async_setup_entry: {config.options}")
    coordinator = hass.data[DOMAIN][config.entry_id]

    descriptions = coordinator.inverter.get_entity_descriptions()

    _LOGGER.debug(f"async_setup: async_add_entities")

    async_add_entities(create_entity(lambda x: SolarmanSwitchEntity(coordinator, x), d) for d in descriptions if is_platform(d, _PLATFORM))

    return True

async def async_unload_entry(hass: HomeAssistant, config: ConfigEntry) -> bool:
    _LOGGER.debug(f"async_unload_entry: {config.options}")

    return True

class SolarmanSwitchEntity(SolarmanEntity, SwitchEntity):
    def __init__(self, coordinator, sensor):
        SolarmanEntity.__init__(self, coordinator, _PLATFORM, sensor)
        self._attr_device_class = SwitchDeviceClass.SWITCH
        if not "control" in sensor:
            self._attr_entity_category = EntityCategory.CONFIG

        self._value_on = 1
        self._value_off = 0
        if "value" in sensor and (value := sensor["value"]):
            if True in value:
                self._value_on = value[True]
            if "on" in value:
                self._value_on = value["on"]
            if False in value:
                self._value_off = value[False]
            if "off" in value:
                self._value_off = value["off"]

        registers = sensor["registers"]
        registers_length = len(registers)
        if registers_length > 0:
            self.register = sensor["registers"][0]
        if registers_length > 1:
            _LOGGER.warning(f"SolarmanSwitchEntity.__init__: Contains more than 1 register!")

    @property
    def is_on(self) -> bool | None:
        """Return True if entity is on."""
        return self._attr_state != self._value_off

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the entity on."""
        if await self.coordinator.inverter.call(CODE.WRITE_MULTIPLE_HOLDING_REGISTERS, self.register, [self._value_on,], ACTION_ATTEMPTS_MAX) > 0:
            self.set_state(1)
            self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the entity off."""
        if await self.coordinator.inverter.call(CODE.WRITE_MULTIPLE_HOLDING_REGISTERS, self.register, [self._value_off,], ACTION_ATTEMPTS_MAX) > 0:
            self.set_state(0)
            self.async_write_ha_state()
