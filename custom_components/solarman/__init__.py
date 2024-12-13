from __future__ import annotations

import logging

from functools import partial

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType
from homeassistant.helpers.entity_registry import async_migrate_entries

from .const import *
from .common import *
from .provider import ConfigurationProvider
from .coordinator import Inverter, InverterCoordinator
from .config_flow import ConfigFlowHandler
from .entity import migrate_unique_ids
from .services import async_register

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.SWITCH, Platform.NUMBER, Platform.SELECT, Platform.DATETIME, Platform.TIME, Platform.BUTTON]

CONFIG_SCHEMA = cv.empty_config_schema(DOMAIN)

async def async_setup(hass: HomeAssistant, _: ConfigType) -> bool:
    _LOGGER.debug(f"async_setup")

    async_register(hass)

    return True

async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    _LOGGER.debug(f"async_setup_entry({config_entry.as_dict()})")

    config = ConfigurationProvider(hass, config_entry)
    coordinator = InverterCoordinator(hass, Inverter(config))

    hass.data.setdefault(DOMAIN, {})[config_entry.entry_id] = coordinator

    # Fetch initial data so we have data when entities subscribe.
    #
    # If the refresh fails, async_config_entry_first_refresh will
    # raise ConfigEntryNotReady and setup will try again later.
    #
    # If you do not want to retry setup on failure, use
    # coordinator.async_refresh() instead.
    #
    _LOGGER.debug(f"async_setup: coordinator.async_config_entry_first_refresh")

    await coordinator.async_config_entry_first_refresh()

    # Migrations
    #
    _LOGGER.debug(f"async_setup: async_migrate_entries")

    await async_migrate_entries(hass, config_entry.entry_id, partial(migrate_unique_ids, config.name, config.serial))

    # Forward setup
    #
    _LOGGER.debug(f"async_setup: hass.config_entries.async_forward_entry_setups: {PLATFORMS}")

    await hass.config_entries.async_forward_entry_setups(config_entry, PLATFORMS)

    # Add update listener
    #
    _LOGGER.debug(f"async_setup: config_entry.add_update_listener(async_update_listener)")

    async def async_update_listener(hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        _LOGGER.debug(f"async_update_listener({config_entry.as_dict()})")
        await hass.config_entries.async_reload(config_entry.entry_id)

    config_entry.async_on_unload(config_entry.add_update_listener(async_update_listener))

    return True

async def async_unload_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    _LOGGER.debug(f"async_unload_entry({config_entry.as_dict()})")

    # Forward setup
    #
    _LOGGER.debug(f"async_setup: hass.config_entries.async_unload_platforms: {PLATFORMS}")

    if unload_ok := await hass.config_entries.async_unload_platforms(config_entry, PLATFORMS):
        _ = hass.data[DOMAIN].pop(config_entry.entry_id)

    return unload_ok

async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    _LOGGER.debug("Migrating configuration from version %s.%s", config_entry.version, config_entry.minor_version)

    #if config_entry.minor_version > 1:
    #    return False

    if (new_data := {**config_entry.data}) and (new_options := {**config_entry.options}):
        bulk_migrate(new_data, new_data, OLD_)
        bulk_migrate(new_options, new_options, OLD_)
        bulk_inherit(new_options.setdefault(CONF_ADDITIONAL_OPTIONS, {}), new_options, CONF_BATTERY_NOMINAL_VOLTAGE, CONF_BATTERY_LIFE_CYCLE_RATING)
        bulk_safe_delete(new_data, OLD_)
        bulk_safe_delete(new_options, OLD_ | to_dict(CONF_BATTERY_NOMINAL_VOLTAGE, CONF_BATTERY_LIFE_CYCLE_RATING))

        if not new_options.get(CONF_ADDITIONAL_OPTIONS):
            del new_options[CONF_ADDITIONAL_OPTIONS]

        hass.config_entries.async_update_entry(config_entry, options = new_options, minor_version = ConfigFlowHandler.MINOR_VERSION, version = ConfigFlowHandler.VERSION)

    _LOGGER.debug("Migration to configuration version %s.%s successful", config_entry.version, config_entry.minor_version)

    return True
