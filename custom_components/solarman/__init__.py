from __future__ import annotations

import socket
import logging

from functools import partial
from ipaddress import IPv4Address, AddressValueError

from homeassistant.const import CONF_NAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity_registry import async_migrate_entries

from .const import *
from .common import *
from .api import Inverter
from .discovery import InverterDiscovery
from .coordinator import InverterCoordinator
from .entity import migrate_unique_ids
from .config_flow import async_update_listener
from .services import *

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.SWITCH, Platform.NUMBER, Platform.SELECT, Platform.DATETIME, Platform.TIME, Platform.BUTTON]

async def async_setup_entry(hass: HomeAssistant, config: ConfigEntry) -> bool:
    _LOGGER.debug(f"async_setup_entry({config.as_dict()})")

    data = config.data
    name = data.get(CONF_NAME)
    serial = data.get(CONF_SERIAL)

    options = config.options
    host = options.get(CONF_HOST, IP_ANY)
    port = options.get(CONF_PORT, DEFAULT_INVERTER_PORT)
    mac = None

    additional = options.get(CONF_ADDITIONAL_OPTIONS, {})
    mb_slave_id = additional.get(CONF_MB_SLAVE_ID, DEFAULT_MB_SLAVE_ID)

    profile = Profile(hass.config.path(LOOKUP_DIRECTORY_PATH), options, additional)

    if serial is None:
        raise vol.Invalid("Configuration parameter [serial] does not have a value")
    if host is None:
        raise vol.Invalid("Configuration parameter [host] does not have a value")
    if port is None:
        raise vol.Invalid("Configuration parameter [port] does not have a value")

    try:
        ipaddr = IPv4Address(host)
    except AddressValueError:
        ipaddr = IPv4Address(socket.gethostbyname(host))
    if ipaddr.is_private and (discover := await InverterDiscovery(hass, host, serial).discover()):
        if (device := discover.get(serial)) is not None:
            host = device["ip"]
            mac = device["mac"]
        elif (device := discover.get((s := next(iter([k for k, v in discover.items() if v["ip"] == host]), None)))):
            raise vol.Invalid(f"Host {host} has serial number {s} but is configured with {serial}.")

    inverter = Inverter(host, serial, port, mb_slave_id)
    coordinator = InverterCoordinator(hass, inverter, partial(inverter.load, name, mac, profile))

    hass.data.setdefault(DOMAIN, {})[config.entry_id] = coordinator

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

    await async_migrate_entries(hass, config.entry_id, partial(migrate_unique_ids, name, serial))

    # Forward setup
    #
    _LOGGER.debug(f"async_setup: hass.config_entries.async_forward_entry_setups: {PLATFORMS}")

    await hass.config_entries.async_forward_entry_setups(config, PLATFORMS)

    config.async_on_unload(config.add_update_listener(async_update_listener))

    register_services(hass)

    return True

async def async_unload_entry(hass: HomeAssistant, config: ConfigEntry) -> bool:
    _LOGGER.debug(f"async_unload_entry({config.as_dict()})")

    remove_services(hass)

    if unload_ok := await hass.config_entries.async_unload_platforms(config, PLATFORMS):
        _ = hass.data[DOMAIN].pop(config.entry_id)

    return unload_ok

async def async_migrate_entry(hass, config_entry: ConfigEntry):
    _LOGGER.debug("Migrating configuration from version %s.%s", config_entry.version, config_entry.minor_version)

    if config_entry.minor_version > 1:
        return False

    if config_entry.minor_version == 1 and (new_data := {**config_entry.data}) and (new_options := {**config_entry.options}):
        bulk_inherit(new_data, new_data, "inverter_serial")
        bulk_inherit(new_options, new_options, "inverter_serial", "inverter_host", "inverter_port")
        bulk_inherit(new_options.setdefault(CONF_ADDITIONAL_OPTIONS, {}), new_options, CONF_BATTERY_NOMINAL_VOLTAGE, CONF_BATTERY_LIFE_CYCLE_RATING)
        bulk_delete(new_data, "inverter_serial")
        bulk_delete(new_options, "inverter_serial", "inverter_host", "inverter_port", CONF_BATTERY_NOMINAL_VOLTAGE, CONF_BATTERY_LIFE_CYCLE_RATING)

        hass.config_entries.async_update_entry(config_entry, options = new_options, minor_version = 2, version = 1)

    _LOGGER.debug("Migration to configuration version %s.%s successful", config_entry.version, config_entry.minor_version)

    return True
