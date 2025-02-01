from __future__ import annotations

import socket
import logging

from typing import Any
from dataclasses import dataclass
from propcache import cached_property
from collections.abc import Awaitable, Callable
from ipaddress import IPv4Address, AddressValueError

from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry

from .const import *
from .common import *
from .discovery import InverterDiscovery
from .parser import ParameterParser

_LOGGER = logging.getLogger(__name__)

@dataclass
class ConfigurationProvider:
    hass: HomeAssistant
    config_entry: ConfigEntry

    @cached_property
    def _data(self):
        return self.config_entry.data

    @cached_property
    def _options(self):
        return self.config_entry.options

    @cached_property
    def _additional_options(self):
        return self._options.get(CONF_ADDITIONAL_OPTIONS, {})

    @cached_property
    def name(self):
        return protected(self._data.get(CONF_NAME), "Configuration parameter [name] does not have a value")

    @cached_property
    def serial(self):
        return protected(self._data.get(CONF_SERIAL, self._data.get(OLD_[CONF_SERIAL])), "Configuration parameter [serial] does not have a value")

    @cached_property
    def host(self):
        return self._options.get(CONF_HOST, IP_ANY)

    @cached_property
    def port(self):
        return self._options.get(CONF_PORT, DEFAULT_[CONF_PORT])

    @cached_property
    def filename(self):
        return self._options.get(CONF_LOOKUP_FILE, DEFAULT_[CONF_LOOKUP_FILE])

    @cached_property
    def mb_slave_id(self):
        return self._additional_options.get(CONF_MB_SLAVE_ID, DEFAULT_[CONF_MB_SLAVE_ID])

    @cached_property
    def directory(self):
        return self.hass.config.path(LOOKUP_DIRECTORY_PATH)

@dataclass
class EndPointProvider:
    config: ConfigurationProvider
    mac: str = ""

    def __getattr__(self, attr: str) -> Any:
        return getattr(self.config, attr)

    @cached_property
    def address(self):
        return self.host

    @cached_property
    def connection(self):
        return self.serial, self.address, self.port, self.mb_slave_id, TIMINGS_TIMEOUT

    @cached_property
    def ipaddress(self):
        try:
            return IPv4Address(self.host)
        except AddressValueError:
            return IPv4Address(socket.gethostbyname(self.host))    

    async def discover(self, ping_only = False):
        if self.ipaddress.is_private and (discover := await InverterDiscovery(self.hass, self.host, self.serial).discover(ping_only)):
            if (device := discover.get(self.serial)) is not None:
                self.host = device["ip"]
                self.mac = device["mac"]
            elif (device := discover.get((s := next(iter([k for k, v in discover.items() if v["ip"] == self.host]), None)))):
                raise vol.Invalid(f"Host {self.host} has serial number {s} but is configured with {self.serial}.")
        return self

@dataclass
class ProfileProvider:
    config: ConfigurationProvider
    endpoint: EndPointProvider
    parser: ParameterParser = None

    def __getattr__(self, attr: str) -> Any:
        return getattr(self.config, attr)

    @cached_property
    def auto(self) -> bool:
        return not self.filename or self.filename in AUTODETECTION_REDIRECT

    @cached_property
    def attributes(self) -> str:
        return {ATTR_[k]: int(self._additional_options.get(k, DEFAULT_[k])) for k in ATTR_}

    async def resolve(self, request: Callable[[], Awaitable[None]] | None = None):
        _LOGGER.debug(f"Device autodetection is {"enabled" if self.auto and request else f"disabled. Selected profile: {self.filename}"}")

        f = lookup_profile(await request(-1, set_request(*AUTODETECTION_REQUEST_DEYE)), self.attributes) if self.auto and request else self.filename

        if f and f != DEFAULT_[CONF_LOOKUP_FILE] and (n := process_profile(f)) and (p := await yaml_open(self.config.directory + n)):
            self.parser = ParameterParser(p, self.attributes)

            return build_device_info(self.serial, self.endpoint.mac, self.name, unwrap(p["info"], "model", self.attributes[ATTR_[CONF_MOD]]) if "info" in p else None, f)

        raise Exception(f"Unable to resolve and process selected profile: {self.filename}")
