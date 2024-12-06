from __future__ import annotations

import logging

from functools import partial

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity_registry import async_migrate_entries

from .const import *
from .common import *
from .provider import *
from .api import Inverter
from .coordinator import InverterCoordinator
from .entity import migrate_unique_ids
from .config_flow import async_update_listener
from .services import *

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.SWITCH, Platform.NUMBER, Platform.SELECT, Platform.DATETIME, Platform.TIME, Platform.BUTTON]

async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    _LOGGER.debug(f"async_setup_entry({config_entry.as_dict()})")

    config = ConfigurationProvider(hass, config_entry)
    coordinator = InverterCoordinator(hass, Inverter(config, await EndPointProvider(config).discover()))
    # TODO: Move construction of EndPointProvider (w/ discover() flow within Inverter.Load())
    #       into construction of Inverter after separation of PySolarmanV5AsyncWrapper

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

    config_entry.async_on_unload(config_entry.add_update_listener(async_update_listener))

    register_services(hass)

    return True

async def async_unload_entry(hass: HomeAssistant, config: ConfigEntry) -> bool:
    _LOGGER.debug(f"async_unload_entry({config.as_dict()})")

    remove_services(hass)

    if unload_ok := await hass.config_entries.async_unload_platforms(config, PLATFORMS):
        _ = hass.data[DOMAIN].pop(config.entry_id)

    return unload_ok

async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    _LOGGER.debug("Migrating configuration from version %s.%s", config_entry.version, config_entry.minor_version)

    #if config_entry.minor_version > 1:
    #    return False

    if (new_data := {**config_entry.data}) and (new_options := {**config_entry.options}):
        bulk_migrate(new_data, new_data, { CONF_SERIAL: "inverter_serial" })

        bulk_migrate(new_options, new_options, { CONF_SERIAL: "inverter_serial", CONF_HOST: "inverter_host", CONF_PORT: "inverter_port" })
        bulk_migrate(new_options.setdefault(CONF_ADDITIONAL_OPTIONS, {}), new_options, CONF_BATTERY_NOMINAL_VOLTAGE, CONF_BATTERY_LIFE_CYCLE_RATING)

        bulk_delete(new_data, "inverter_serial")
        bulk_delete(new_options, "inverter_serial", "inverter_host", "inverter_port", CONF_BATTERY_NOMINAL_VOLTAGE, CONF_BATTERY_LIFE_CYCLE_RATING)

        hass.config_entries.async_update_entry(config_entry, options = new_options, minor_version = 2, version = 1)

    _LOGGER.debug("Migration to configuration version %s.%s successful", config_entry.version, config_entry.minor_version)

    return True
