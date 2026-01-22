from __future__ import annotations

from typing import Any
from logging import getLogger
from dataclasses import dataclass
from propcache import cached_property
from collections.abc import Awaitable, Callable

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry

from .const import *
from .common import *
from .discovery import discover
from .parser import ParameterParser

_LOGGER = getLogger(__name__)

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
    info: str = None

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
        return getipaddress(self.host) 

    async def init(self):
        await self.discover()
        return self

    async def discover(self):
        try:
            if "modbus" not in self.transport and self.ip.is_private and (d := await anext((v async for v in await discover(self.hass, str(self.ip)) if v["ip"] == str(self.ip)))):
                self.serial = d["serial"]
                self.host = d["ip"]
                self.mac = d["mac"]
                self.info = await request(self.host, LOGGER_SET)
                if next(iter(LOGGER_REGEX["setting_protocol"].finditer(self.info))).group(1) != "TCP" if "tcp" in self.transport else "UDP" or next(iter(LOGGER_REGEX["setting_cs"].finditer(self.info))).group(1) != "SERVER" if "tcp" in self.transport else "" or next(iter(LOGGER_REGEX["setting_port"].finditer(self.info))).group(1) != self.port or next(iter(LOGGER_REGEX["setting_ip"].finditer(self.info))).group(1) != IP_ANY or next(iter(LOGGER_REGEX["setting_timeout"].finditer(self.info))).group(1) != "300":
                    await request(self.host, LOGGER_CMD, LOGGER_SET,
                        {
                            "net_setting_pro": "TCP" if "tcp" in self.transport else "UDP",
                            "net_setting_cs": "SERVER" if "tcp" in self.transport else "",
                            "net_setting_pro_sel": "TCPSERVER" if "tcp" in self.transport else "UDP",
                            "net_setting_port": self.port,
                            "net_setting_ip": "0.0.0.0",
                            "net_setting_to": "300"
                        }
                    )
                    await request(self.host, LOGGER_SUCCESS, LOGGER_CMD, LOGGER_RESTART_DATA)
        except Exception as e:
            _LOGGER.debug(f"[{self.host}] Error", exc_info = True)

    async def load(self):
        try:
            self.info = await request(self.host, LOGGER_SET)
        except Exception as e:
            _LOGGER.debug(f"[{self.host}] Error", exc_info = True)

@dataclass
class ProfileProvider:
    config: ConfigurationProvider
    endpoint: EndPointProvider
    parser: ParameterParser | None = None

    def __getattr__(self, attr: str):
        return getattr(self.config, attr)

    @cached_property
    def auto(self):
        return not self.filename or self.filename in AUTODETECTION_REDIRECT

    @cached_property
    def parameters(self):
        return {PARAM_[k]: int(self._additional_options.get(k, DEFAULT_[k])) for k in PARAM_}

    @cached_property
    def info(self):
        return self.parser.info

    async def init(self, request: Callable[[int, dict], Awaitable[dict]] | None = None):
        if (f := await lookup_profile(request, self.parameters) if self.auto else self.filename) and f != DEFAULT_[CONF_LOOKUP_FILE] and (n := process_profile(f, self.parameters)):
            self.parser = await ParameterParser().init(self.config.directory, n, self.parameters)
        return self
