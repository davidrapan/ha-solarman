from __future__ import annotations

from logging import getLogger

from homeassistant.core import HomeAssistant
from homeassistant.const import EntityCategory
from homeassistant.config_entries import ConfigEntry
from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import *
from .common import *
from .services import *
from .entity import SolarmanEntity, SolarmanWritableEntity, Coordinator

_LOGGER = getLogger(__name__)

_PLATFORM = get_current_file_name(__name__)

async def async_setup_entry(_: HomeAssistant, config_entry: ConfigEntry[Coordinator], async_add_entities: AddEntitiesCallback) -> bool:
    _LOGGER.debug(f"async_setup_entry: {config_entry.options}")

    async_add_entities([SolarmanCloud(config_entry.runtime_data)] + [SolarmanSelectEntity(config_entry.runtime_data, d).init() for d in postprocess_descriptions(config_entry.runtime_data, _PLATFORM)])

    return True

async def async_unload_entry(_: HomeAssistant, config_entry: ConfigEntry[Coordinator]) -> bool:
    _LOGGER.debug(f"async_unload_entry: {config_entry.options}")

    return True

class SolarmanCloud(SolarmanEntity, SelectEntity):
    def __init__(self, coordinator):
        SolarmanEntity.__init__(self, coordinator, {"key": "cloud_select", "name": "Cloud"})
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_options = ["Disabled", "HTTP", "HTTPS"]
        self._attr_icon = "mdi:cloud-upload-outline"

    @property
    def available(self):
        return self.coordinator.device.endpoint.info is not None and self.current_option is not None

    @property
    def current_option(self):
        for i in LOGGER_REGEX["server"].finditer(self.coordinator.device.endpoint.info):
            match i.group(1):
                case c if c.endswith("5406.deviceaccess.host,10443,TCP"):
                    return "HTTPS"
                case c if c.endswith("5406.deviceaccess.host,10000,TCP"):
                    return "HTTP"
                case c if c.startswith(",,"):
                    return "Disabled"
        return None

    async def async_select_option(self, option: str):
        await self.coordinator.device.endpoint.load()
        if self.is_on is True:
            await request(f"http://{self.coordinator.device.config.host}/{LOGGER_CMD}", auth = LOGGER_AUTH, data = FormData(logger_set_data(option != "Disabled", 10443 if option == "HTTPS" else 10000)), headers = {"Referer": f"http://{self.coordinator.device.config.host}/{LOGGER_SET}"})
            await self.coordinator.device.endpoint.load()
            await request(f"http://{self.coordinator.device.config.host}/{LOGGER_SUCCESS}", auth = LOGGER_AUTH, data = LOGGER_RESTART_DATA, headers = {"Referer": f"http://{self.coordinator.device.config.host}/{LOGGER_CMD}"})
        self.async_write_ha_state()

class SolarmanSelectEntity(SolarmanWritableEntity, SelectEntity):
    def __init__(self, coordinator, sensor):
        SolarmanWritableEntity.__init__(self, coordinator, sensor)

        self.mask = display.get("mask") if (display := sensor.get("display")) else None

        if "lookup" in sensor:
            self.dictionary = sensor["lookup"]

        if len(self.registers) > 1:
            _LOGGER.warning(f"SolarmanSelectEntity.__init__: {self._attr_name} contains {len(self.registers)} registers!")

    def get_key(self, value: str):
        if self.dictionary:
            for o in self.dictionary:
                if o["value"] == value and (key := from_bit_index(o["bit"]) if "bit" in o else o["key"]) is not None:
                    return (key if not "mode" in o else (self._attr_value | key)) if not self.mask else (self._attr_value & (0xFFFFFFFF - self.mask) | key)

        return self.options.index(value)

    @property
    def current_option(self):
        """Return the current option of this select."""
        return self._attr_state if not self.mask else lookup_value(self._attr_value & self.mask, self.dictionary)

    async def async_select_option(self, option: str):
        """Change the selected option."""
        await self.write(self.get_key(option), option)
