from __future__ import annotations

import socket
import asyncio

from logging import getLogger
from typing import AsyncGenerator
from ipaddress import IPv4Network
from datetime import datetime, timedelta

from homeassistant import config_entries
from homeassistant.components import network
from homeassistant.helpers import singleton, discovery_flow
from homeassistant.core import HomeAssistant, callback

from .const import *
from .common import *

_LOGGER = getLogger(__name__)

class DiscoveryProtocol:
    def __init__(self, addresses: list[str] | str):
        self.addresses = addresses
        self.responses = asyncio.Queue()

    def connection_made(self, transport: asyncio.DatagramTransport):
        _LOGGER.debug(f"DiscoveryProtocol: Send to {self.addresses}")
        for address in ensure_list(self.addresses):
            for message in DISCOVERY_MESSAGE:
                transport.sendto(message, (address, DISCOVERY_PORT))

    def datagram_received(self, data: bytes, addr: tuple[str, int]):
        if len(d := data.decode().split(',')) == 3 and (s := int(d[2])):
            self.responses.put_nowait((s, {"ip": d[0], "mac": d[1]}))
            _LOGGER.debug(f"DiscoveryProtocol: [{d[0]}, {d[1]}, {s}] from {addr}")

    def error_received(self, e: OSError):
        _LOGGER.debug(f"DiscoveryProtocol: {strepr(e)}")

    def connection_lost(self, _):
        pass

class Discovery:
    def __init__(self, hass: HomeAssistant):
        self._semaphore = asyncio.Semaphore(1)
        self._networks: list[IPv4Network] | None = None
        self._devices: dict[int, dict[str, str]] = {}
        self._when: datetime | None = None
        self._hass = hass

    async def init(self):
        self._networks = [n for adapter in await network.async_get_adapters(self._hass) if adapter["enabled"] and adapter["index"] is not None and adapter["ipv4"] for ip in adapter["ipv4"] if (n := IPv4Network(ip["address"] + '/' + str(ip["network_prefix"]), False)) and not n.is_loopback and not n.is_global]
        return self

    async def _discover(self, addresses: list[str] | str = IP_BROADCAST, wait: bool = False) -> AsyncGenerator[tuple[int, dict[str, str]], None]:
        try:
            transport, protocol = await asyncio.get_running_loop().create_datagram_endpoint(lambda: DiscoveryProtocol(addresses), family = socket.AF_INET, allow_broadcast = True)
            while (r := await asyncio.wait_for(protocol.responses.get(), DISCOVERY_TIMEOUT)) or wait:
                yield r
        except TimeoutError:
            pass
        except Exception as e:
            _LOGGER.debug(f"_discover: {strepr(e)}")
        finally:
            transport.close()

    async def discover(self, address: str | None = None):
        devices: dict[int, dict[str, str]] = {}
        async with self._semaphore:
            if self._devices and (datetime.now() - self._when) < DISCOVERY_CACHE:
                devices = self._devices
            if address and not (devices and any([v["ip"] == address for v in devices.values()])):
                devices = {k: v async for k, v in self._discover(address)}
            if not devices:
                self._devices = devices = {k: v async for k, v in self._discover([str(net.broadcast_address) for net in self._networks], True)}
                self._when = datetime.now()
        return devices

@singleton.singleton(f"{DOMAIN}_discovery")
async def get_discovery(hass: HomeAssistant):
    return await Discovery(hass).init()

async def discover(hass: HomeAssistant, address: str | None = None):
    return await (await get_discovery(hass)).discover(address)

@callback
async def trigger_discovery(hass: HomeAssistant):
    for k, v in (await discover(hass)).items():
        discovery_flow.async_create_flow(hass, DOMAIN, context = {"source": config_entries.SOURCE_INTEGRATION_DISCOVERY}, data = dict(v, serial = k))
