from __future__ import annotations

import socket

from typing import Any
from dataclasses import dataclass
from propcache import cached_property
from collections.abc import Awaitable, Callable
from ipaddress import IPv4Address, AddressValueError

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry

from .const import *
from .common import *
from .discovery import discover
from .parser import ParameterParser

@dataclass
class ConfigurationProvider:
    hass: HomeAssistant
    config_entry: ConfigEntry

    @cached_property
    def _options(self):
        return self.config_entry.options

    @cached_property
    def _additional_options(self):
        return self._options.get(CONF_ADDITIONAL_OPTIONS, {})

    @cached_property
    def name(self):
        return protected(self.config_entry.title, "Configuration parameter [title] does not have a value")

    @cached_property
    def host(self) -> str:
        return protected(self._options.get(CONF_HOST), "Configuration parameter [host] does not have a value")

    @cached_property
    def port(self) -> int:
        return self._options.get(CONF_PORT, DEFAULT_[CONF_PORT])

    @cached_property
    def transport(self) -> str:
        return self._options.get(CONF_TRANSPORT, DEFAULT_[CONF_TRANSPORT])

    @cached_property
    def filename(self) -> str:
        return self._options.get(CONF_LOOKUP_FILE, DEFAULT_[CONF_LOOKUP_FILE])

    @cached_property
    def mb_slave_id(self) -> int:
        return self._additional_options.get(CONF_MB_SLAVE_ID, DEFAULT_[CONF_MB_SLAVE_ID])

    @cached_property
    def directory(self):
        return self.hass.config.path(LOOKUP_DIRECTORY_PATH)

@dataclass
class EndPointProvider:
    config: ConfigurationProvider
    mac = ""
    serial = 0

    def __getattr__(self, attr: str) -> Any:
        return getattr(self.config, attr)

    @cached_property
    def host(self):
        return self.config.host

    @cached_property
    def connection(self) -> tuple[str, int, str, int, int, int]:
        return self.host, self.port, self.transport, self.serial, self.mb_slave_id, TIMINGS_INTERVAL

    @cached_property
    def ip(self):
        try:
            return IPv4Address(self.host)
        except AddressValueError:
            return IPv4Address(socket.gethostbyname(self.host))    

    async def discover(self):
        if self.ip.is_private and (devices := await discover(self.hass, str(self.ip))):
            if (device := devices.get((s := next(iter([k for k, v in devices.items() if v["ip"] == str(self.ip)]), None)))) is not None:
                self.host = device["ip"]
                self.mac = device["mac"]
                self.serial = s
        return self

@dataclass
class ProfileProvider:
    config: ConfigurationProvider
    endpoint: EndPointProvider
    info: dict[str, str] | None = None
    parser: ParameterParser | None = None

    def __getattr__(self, attr: str):
        return getattr(self.config, attr)

    @cached_property
    def auto(self):
        return not self.filename or self.filename in AUTODETECTION_REDIRECT

    @cached_property
    def parameters(self):
        return {PARAM_[k]: int(self._additional_options.get(k, DEFAULT_[k])) for k in PARAM_}

    async def resolve(self, request: Callable[[int, dict], Awaitable[dict]] | None = None):
        if (f := await lookup_profile(request, self.parameters) if self.auto else self.filename) and f != DEFAULT_[CONF_LOOKUP_FILE] and (n := process_profile(f, self.parameters)) and (p := await yaml_open(self.config.directory + n)):
            self.info = (unwrap(p["info"], "model", self.parameters[PARAM_[CONF_MOD]]) if "info" in p else {}) | {"filename": f}
            self.parser = ParameterParser(p, self.parameters)
