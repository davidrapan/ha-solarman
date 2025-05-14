from __future__ import annotations

import logging

from functools import partial

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.helpers.typing import ConfigType
from homeassistant.helpers.entity_registry import async_migrate_entries

from .const import *
from .common import *
from .config_flow import ConfigFlowHandler
from .provider import ConfigurationProvider
from .coordinator import Device, Coordinator
from .entity import SolarmanConfigEntry, migrate_unique_ids
from .services import async_register

_LOGGER = logging.getLogger(__name__)

_PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.NUMBER, Platform.SWITCH, Platform.BUTTON, Platform.SELECT, Platform.DATETIME, Platform.TIME]

CONFIG_SCHEMA = cv.empty_config_schema(DOMAIN)

async def async_setup(hass: HomeAssistant, _: ConfigType) -> bool:
    _LOGGER.debug(f"async_setup")

    async_register(hass)

    return True

async def async_setup_entry(hass: HomeAssistant, config_entry: SolarmanConfigEntry) -> bool:
    _LOGGER.debug(f"async_setup_entry({config_entry.as_dict()})")

    config = ConfigurationProvider(hass, config_entry)
    config_entry.runtime_data = Coordinator(hass, Device(config))

    # Fetch initial data so we have data when entities subscribe.
    #
    # If the refresh fails, async_config_entry_first_refresh will
    # raise ConfigEntryNotReady and setup will try again later.
    #
    # If you do not want to retry setup on failure, use
    # config_entry.runtime_data.async_refresh() instead.
    #
    _LOGGER.debug(f"async_setup_entry: config_entry.runtime_data.async_config_entry_first_refresh")

    await config_entry.runtime_data.async_config_entry_first_refresh()

    # Migrations
    #
    _LOGGER.debug(f"async_setup_entry: async_migrate_entries")

    await async_migrate_entries(hass, config_entry.entry_id, partial(migrate_unique_ids, config_entry))

    # Forward setup
    #
    _LOGGER.debug(f"async_setup_entry: hass.config_entries.async_forward_entry_setups: {_PLATFORMS}")

    await hass.config_entries.async_forward_entry_setups(config_entry, _PLATFORMS)

    # Add update listener
    #
    _LOGGER.debug(f"async_setup_entry: config_entry.add_update_listener(async_update_listener)")

    async def async_update_listener(hass: HomeAssistant, config_entry: SolarmanConfigEntry) -> None:
        _LOGGER.debug(f"async_update_listener({config_entry.as_dict()})")
        await hass.config_entries.async_reload(config_entry.entry_id)

    config_entry.async_on_unload(config_entry.add_update_listener(async_update_listener))

    return True

async def async_unload_entry(hass: HomeAssistant, config_entry: SolarmanConfigEntry) -> bool:
    _LOGGER.debug(f"async_unload_entry({config_entry.as_dict()})")

    # Forward unload
    #
    _LOGGER.debug(f"async_unload_entry: hass.config_entries.async_unload_platforms: {_PLATFORMS}")

    return await hass.config_entries.async_unload_platforms(config_entry, _PLATFORMS)

async def async_migrate_entry(hass: HomeAssistant, config_entry: SolarmanConfigEntry) -> bool:
    _LOGGER.debug(f"async_migrate_entry({config_entry.as_dict()})")

    #if config_entry.minor_version > 1:
    #    return False

    _LOGGER.info("Migrating configuration from version %s.%s", config_entry.version, config_entry.minor_version)

    if (new_data := {**config_entry.data}) and (new_options := {**config_entry.options}):
        bulk_migrate(new_data, new_data, OLD_)
        bulk_migrate(new_options, new_options, OLD_)
        bulk_inherit(new_options.setdefault(CONF_ADDITIONAL_OPTIONS, {}), new_options, CONF_BATTERY_NOMINAL_VOLTAGE, CONF_BATTERY_LIFE_CYCLE_RATING)
        if new_options.get("sn", new_data.get("sn", 1)) == 0:
            new_options[CONF_TRANSPORT] = "modbus_tcp"
        bulk_safe_delete(new_data, OLD_)
        bulk_safe_delete(new_options, OLD_ | to_dict(CONF_BATTERY_NOMINAL_VOLTAGE, CONF_BATTERY_LIFE_CYCLE_RATING))

        if not new_options.get(CONF_ADDITIONAL_OPTIONS):
            del new_options[CONF_ADDITIONAL_OPTIONS]

        hass.config_entries.async_update_entry(config_entry, unique_id = None, data = new_data, options = new_options, minor_version = ConfigFlowHandler.MINOR_VERSION, version = ConfigFlowHandler.VERSION)

    _LOGGER.info("Migration to configuration version %s.%s was successful", config_entry.version, config_entry.minor_version)

    return True

async def async_remove_config_entry_device(hass: HomeAssistant, config_entry: SolarmanConfigEntry, device_entry: dr.DeviceEntry) -> bool:
    _LOGGER.debug(f"async_remove_config_entry_device({config_entry.as_dict()}, {device_entry})")

    return not any(identifier for identifier in device_entry.identifiers if identifier[0] == DOMAIN and identifier[1] == config_entry.entry_id or identifier[1] == config_entry.runtime_data.device.modbus.serial)
