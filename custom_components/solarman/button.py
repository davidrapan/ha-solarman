from __future__ import annotations

from logging import getLogger

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, STATE_OFF, STATE_ON
from homeassistant.components.button import ButtonEntity, ButtonDeviceClass, ButtonEntityDescription
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import *
from .common import *
from .services import *
from .entity import SolarmanEntity, SolarmanWritableEntity, Coordinator

_LOGGER = getLogger(__name__)

_PLATFORM = get_current_file_name(__name__)

async def async_setup_entry(_: HomeAssistant, config_entry: ConfigEntry[Coordinator], async_add_entities: AddEntitiesCallback) -> bool:
    _LOGGER.debug(f"async_setup_entry: {config_entry.options}")

    async_add_entities([SolarmanRestart(config_entry.runtime_data)] + [SolarmanButtonEntity(config_entry.runtime_data, d).init() for d in config_entry.runtime_data.device.profile.parser.get_entity_descriptions(_PLATFORM)])

    return True

async def async_unload_entry(_: HomeAssistant, config_entry: ConfigEntry[Coordinator]) -> bool:
    _LOGGER.debug(f"async_unload_entry: {config_entry.options}")

    return True

class SolarmanRestart(SolarmanEntity, ButtonEntity):
    def __init__(self, coordinator):
        SolarmanEntity.__init__(self, coordinator, {"key": "restart_button", "name": "Restart"})
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_icon = "mdi:restart"

    @property
    def available(self) -> bool:
        return self.coordinator.device.endpoint.info is not None

    async def async_press(self):
        await request(self.coordinator.device.config.host, LOGGER_RESTART)
        await request(self.coordinator.device.config.host, LOGGER_SUCCESS, LOGGER_RESTART, LOGGER_RESTART_DATA)

class SolarmanButtonEntity(SolarmanWritableEntity, ButtonEntity):
    def __init__(self, coordinator, sensor):
        SolarmanWritableEntity.__init__(self, coordinator, sensor)

        self._value = 1
        self._value_bit = None
        if "value" in sensor and (value := sensor["value"]) and not isinstance(value, int):
            if True in value:
                self._value = value[True]
            if "on" in value:
                self._value = value["on"]
            if "bit" in value:
                self._value_bit = value["bit"]

    def _to_native_value(self, value: int) -> int:
        if self._value_bit:
            return (self._get_attr_native_value & ~(1 << self._value_bit)) | (value << self._value_bit) 
        return value

    async def async_press(self):
        """Handle the button press."""
        await self.write(self._to_native_value(self._value))
