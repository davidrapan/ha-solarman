from __future__ import annotations

from pathlib import Path
from logging import getLogger
from datetime import datetime

from homeassistant import loader
from homeassistant.const import Platform
from homeassistant.helpers.typing import ConfigType
from homeassistant.helpers.device_registry import DeviceEntry
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers import config_validation, discovery_flow
from homeassistant.helpers.entity_registry import RegistryEntry, async_get, async_migrate_entries
from homeassistant.config_entries import ConfigEntry, SOURCE_INTEGRATION_DISCOVERY
from homeassistant.core import HomeAssistant, callback, split_entity_id

from .const import *
from .common import *
from .services import register
from .discovery import discover
from .coordinator import Coordinator
from .config_flow import ConfigFlowHandler

_LOGGER = getLogger(__name__)

_DIRECTORY = Path(__file__).parent
_PLATFORMS = [i for i in Platform._member_map_.values() if _DIRECTORY.joinpath(i.value + ".py").is_file()]

CONFIG_SCHEMA = config_validation.empty_config_schema(DOMAIN)

async def async_setup(hass: HomeAssistant, _: ConfigType):
    _LOGGER.debug(f"async_setup")

    try:
        _LOGGER.info(f"Solarman {str((await loader.async_get_integration(hass, DOMAIN)).version)}")
    except loader.IntegrationNotFound as e:
        _LOGGER.debug(f"Error reading version: {strepr(e)}")

    register(hass)

    async def discovery(*_: datetime):
        async for v in await discover(hass):
            discovery_flow.async_create_flow(hass, DOMAIN, context = {"source": SOURCE_INTEGRATION_DISCOVERY}, data = v)

    hass.async_create_background_task(discovery(), "Solarman setup discovery")

    async_track_time_interval(hass, discovery, DISCOVERY_INTERVAL, cancel_on_shutdown = True)

    return True

async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry[Coordinator]):
    _LOGGER.debug(f"async_setup_entry({config_entry.as_dict()})")

    # Initiaize coordinator and fetch initial data
    #
    _LOGGER.debug(f"async_setup_entry: Coordinator.init -> async_config_entry_first_refresh")

    config_entry.runtime_data = await Coordinator(hass, config_entry).init()

    # Migrations
    #
    _LOGGER.debug(f"async_setup_entry: async_migrate_entries")

    @callback
    def migrate(entity_entry: RegistryEntry):
        if entity_entry.unique_id != (unique_id := slugify(config_entry.entry_id, entity_entry.original_name if entity_entry.has_entity_name or not entity_entry.original_name else entity_entry.original_name.replace(config_entry.title, '').strip(), split_entity_id(entity_entry.entity_id)[0])):
            if conflict_entity_id := async_get(hass).async_get_entity_id(entity_entry.domain, entity_entry.platform, unique_id):
                _LOGGER.debug(f"Unique id '{unique_id}' is already in use by '{conflict_entity_id}'")
                return None
            _LOGGER.debug(f"Migrating unique_id for {entity_entry.entity_id} entity from '{entity_entry.unique_id}' to '{unique_id}'")
            return { "new_unique_id": entity_entry.unique_id.replace(entity_entry.unique_id, unique_id) }
        return None

    await async_migrate_entries(hass, config_entry.entry_id, migrate)

    # Forward setup
    #
    _LOGGER.debug(f"async_setup_entry: hass.config_entries.async_forward_entry_setups: {_PLATFORMS}")

    await hass.config_entries.async_forward_entry_setups(config_entry, _PLATFORMS)

    # Add update listener
    #
    _LOGGER.debug(f"async_setup_entry: config_entry.async_on_unload(config_entry.add_update_listener(reload))")

    async def reload(hass: HomeAssistant, config_entry: ConfigEntry[Coordinator]):
        _LOGGER.debug(f"reload({config_entry.as_dict()})")
        await hass.config_entries.async_reload(config_entry.entry_id)

    config_entry.async_on_unload(config_entry.add_update_listener(reload))

    return True

async def async_unload_entry(hass: HomeAssistant, config_entry: ConfigEntry[Coordinator]):
    _LOGGER.debug(f"async_unload_entry({config_entry.as_dict()})")

    # Forward unload
    #
    _LOGGER.debug(f"async_unload_entry: hass.config_entries.async_unload_platforms: {_PLATFORMS}")

    return await hass.config_entries.async_unload_platforms(config_entry, _PLATFORMS)

async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry[Coordinator]):
    _LOGGER.debug(f"async_migrate_entry({config_entry.as_dict()})")
    _LOGGER.info("Migrating configuration version %s.%s to %s.%s", config_entry.version, config_entry.minor_version, ConfigFlowHandler.VERSION, ConfigFlowHandler.MINOR_VERSION)

    if (new_data := {**config_entry.data}) is not None and (new_options := {**config_entry.options}) is not None:
        bulk_migrate(new_data, new_data, OLD_)
        bulk_migrate(new_options, new_options, OLD_)
        bulk_inherit(new_options.setdefault(CONF_ADDITIONAL_OPTIONS, {}), new_options, CONF_BATTERY_NOMINAL_VOLTAGE, CONF_BATTERY_LIFE_CYCLE_RATING)
        if new_options.get("sn", new_data.get("sn", 1)) == 0:
            new_options[CONF_TRANSPORT] = "modbus_tcp"
        bulk_safe_delete(new_data, OLD_)
        bulk_safe_delete(new_options, OLD_ | to_dict(CONF_BATTERY_NOMINAL_VOLTAGE, CONF_BATTERY_LIFE_CYCLE_RATING))
        if a := new_options.get(CONF_ADDITIONAL_OPTIONS):
            if isinstance(m := a.get(CONF_MOD), bool):
                m = int(m)
        else:
            del new_options[CONF_ADDITIONAL_OPTIONS]
        hass.config_entries.async_update_entry(config_entry, unique_id = None, data = new_data, options = new_options, minor_version = ConfigFlowHandler.MINOR_VERSION, version = ConfigFlowHandler.VERSION)

    return True

async def async_remove_config_entry_device(_: HomeAssistant, config_entry: ConfigEntry[Coordinator], device_entry: DeviceEntry):
    _LOGGER.debug(f"async_remove_config_entry_device({config_entry.as_dict()}, {device_entry})")

    return not (config_entry.entry_id == device_entry.primary_config_entry or any(identifier for identifier in device_entry.identifiers if identifier[0] == DOMAIN and (identifier[1] == config_entry.entry_id or identifier[1] == config_entry.runtime_data.device.modbus.serial)))
