from __future__ import annotations

import socket
import logging

from ipaddress import IPv4Address, AddressValueError

from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry

from .const import *
from .common import *
from .api import Inverter
from .discovery import InverterDiscovery
from .coordinator import InverterCoordinator
from .config_flow import async_update_listener
from .services import *

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, config: ConfigEntry) -> bool:
    _LOGGER.debug(f"async_setup_entry({config.as_dict()})")

    options = config.options

    name = options.get(CONF_NAME)

    inverter_host = options.get(CONF_INVERTER_HOST)
    inverter_serial = options.get(CONF_INVERTER_SERIAL)
    inverter_port = options.get(CONF_INVERTER_PORT)
    inverter_mb_slave_id = options.get(CONF_INVERTER_MB_SLAVE_ID)
    inverter_mac = None

    lookup_path = hass.config.path(LOOKUP_DIRECTORY_PATH)
    lookup_file = options.get(CONF_LOOKUP_FILE)

    try:
        ipaddr = IPv4Address(inverter_host)
    except AddressValueError:
        ipaddr = IPv4Address(socket.gethostbyname(inverter_host))
    if ipaddr.is_private and (device := get_or_default(await InverterDiscovery(hass, inverter_host, inverter_serial).discover(), inverter_serial)):
        inverter_host = device["ip"]
        inverter_mac = device["mac"]

    if inverter_host is None:
        raise vol.Invalid("Configuration parameter [inverter_host] does not have a value")
    if inverter_serial is None:
        raise vol.Invalid("Configuration parameter [inverter_serial] does not have a value")
    if inverter_port is None:
        raise vol.Invalid("Configuration parameter [inverter_port] does not have a value")
    if inverter_mb_slave_id is None:
        inverter_mb_slave_id = DEFAULT_INVERTER_MB_SLAVE_ID
    if lookup_file is None:
        raise vol.Invalid("Configuration parameter [lookup_file] does not have a value")

    inverter = Inverter(inverter_host, inverter_serial, inverter_port, inverter_mb_slave_id)

    await inverter.load(name, inverter_mac, lookup_path, lookup_file)

    coordinator = InverterCoordinator(hass, inverter)

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

    # Forward setup
    #
    _LOGGER.debug(f"hass.config_entries.async_forward_entry_setups: {PLATFORMS}")

    await hass.config_entries.async_forward_entry_setups(config, PLATFORMS)
    config.async_on_unload(config.add_update_listener(async_update_listener))

    register_services(hass)

    return True

async def async_unload_entry(hass: HomeAssistant, config: ConfigEntry) -> bool:
    _LOGGER.debug(f"async_unload_entry({config.as_dict()})")

    if unload_ok := await hass.config_entries.async_unload_platforms(config, PLATFORMS):
        _ = hass.data[DOMAIN].pop(config.entry_id)

    remove_services(hass)

    return unload_ok
