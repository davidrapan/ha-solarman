from __future__ import annotations

from logging import getLogger

from homeassistant.core import HomeAssistant
from homeassistant.const import EntityCategory
from homeassistant.config_entries import ConfigEntry
from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import *
from .common import *
from .services import *
from .entity import SolarmanEntity, SolarmanWritableEntity, Coordinator

_LOGGER = getLogger(__name__)

_PLATFORM = get_current_file_name(__name__)

async def async_setup_entry(_: HomeAssistant, config_entry: ConfigEntry[Coordinator], async_add_entities: AddEntitiesCallback) -> bool:
    _LOGGER.debug(f"async_setup_entry: {config_entry.options}")

    async_add_entities([SolarmanMode(config_entry.runtime_data), SolarmanCloud(config_entry.runtime_data)] + [SolarmanSelectEntity(config_entry.runtime_data, d).init() for d in config_entry.runtime_data.device.profile.parser.get_entity_descriptions(_PLATFORM)])

    return True

async def async_unload_entry(_: HomeAssistant, config_entry: ConfigEntry[Coordinator]) -> bool:
    _LOGGER.debug(f"async_unload_entry: {config_entry.options}")

    return True

class SolarmanMode(SolarmanEntity, SelectEntity):
    def __init__(self, coordinator):
        SolarmanEntity.__init__(self, coordinator, {"key": "mode_select", "name": "Mode"})
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_options = ["Data collection", "Transparency"]

    @property
    def available(self):
        return self.coordinator.device.endpoint.info is not None and self.current_option is not None

    @property
    def current_option(self):
        for i in LOGGER_REGEX["mode"].finditer(self.coordinator.device.endpoint.info):
            match i.group(1):
                case "cmd":
                    return "Data collection"
                case "throughput":
                    return "Transparency"
        return None

    async def async_select_option(self, option: str):
        await self.coordinator.device.endpoint.load()
        if option:
            await request(self.coordinator.device.config.host, LOGGER_CMD, LOGGER_SET, {"yz_tmode": "cmd" if option == "Data collection" else "throughput"})
            await self.coordinator.device.endpoint.load()
            await request(self.coordinator.device.config.host, LOGGER_SUCCESS, LOGGER_CMD, LOGGER_RESTART_DATA)
        self.async_write_ha_state()

class SolarmanCloud(SolarmanEntity, SelectEntity, RestoreEntity):
    def __init__(self, coordinator):
        SolarmanEntity.__init__(self, coordinator, {"key": "cloud_select", "name": "Cloud"})
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_options = ["Disabled", "Enabled", "Encrypted"]
        self._attr_icon = "mdi:cloud-upload-outline"

    @property
    def available(self):
        return self.coordinator.device.endpoint.info is not None and self.current_option is not None

    @property
    def current_option(self):
        endpoints: list[str] = []
        for i in LOGGER_REGEX["server"].finditer(self.coordinator.device.endpoint.info):
            if (value := i.group(1)) and not value.startswith(",,") and (endpoint := value.split(",")) and endpoint not in endpoints:
                endpoints.append(endpoint)
        if endpoints:
            self._attr_extra_state_attributes["endpoints"] = endpoints
            return "Enabled" if not endpoints[0][2].endswith("443") else "Encrypted"
        if self._attr_extra_state_attributes.get("endpoints"):
            return "Disabled"
        return None

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        if (state := await self.async_get_last_state()) and "endpoints" in state.attributes:
            self._attr_extra_state_attributes["endpoints"] = state.attributes["endpoints"]

    async def async_select_option(self, option: str):
        await self.coordinator.device.endpoint.load()
        if (disabled := option == "Disabled") or (endpoints := self._attr_extra_state_attributes["endpoints"]):
            address_a, domain_a, port_a, protocol_a = endpoints[0]
            address_b, domain_b, port_b, protocol_b = endpoints[1] if len(endpoints) > 1 else ("", "", "", "TCP")
            await request(self.coordinator.device.config.host, LOGGER_CMD, LOGGER_SET,
                {
                    "server_a": ",,,TCP" if disabled else f"{address_a},{domain_a},{port_a},{protocol_a}",
                    "cnmo_ip_a": "" if disabled else address_a,
                    "cnmo_ds_a": "" if disabled else domain_a,
                    "cnmo_pt_a": "" if disabled else port_a,
                    "cnmo_tp_a": "TCP" if disabled else protocol_a,
                    "server_b": ",,,TCP" if disabled else f"{address_b},{domain_b},{port_b},{protocol_b}",
                    "cnmo_ip_b": "" if disabled else address_b,
                    "cnmo_ds_b": "" if disabled else domain_b,
                    "cnmo_pt_b": "" if disabled else port_b,
                    "cnmo_tp_b": "TCP" if disabled else protocol_b
                }
            )
            await self.coordinator.device.endpoint.load()
            await request(self.coordinator.device.config.host, LOGGER_SUCCESS, LOGGER_CMD, LOGGER_RESTART_DATA)
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
        try:
            return self._attr_state if not self.mask else lookup_value(self._attr_value & self.mask, self.dictionary)
        except Exception as e:
            _LOGGER.debug(f"SolarmanSelectEntity.current_option of {self._attr_name} w/ {self._attr_value}: {strepr(e)}")
        return None

    async def async_select_option(self, option: str):
        """Change the selected option."""
        await self.write(self.get_key(option), option)
