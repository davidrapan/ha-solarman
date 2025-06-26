from __future__ import annotations

import socket
import asyncio

from logging import getLogger
from typing import AsyncGenerator
from ipaddress import IPv4Network
from datetime import datetime, timedelta

from homeassistant import config_entries
from homeassistant.components import network
from homeassistant.helpers import discovery_flow
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
        _LOGGER.debug(f"DiscoveryProtocol: {e!r}")

    def connection_lost(self, _):
        pass

class Discovery:
    semaphore = asyncio.Semaphore(1)
    networks: list[IPv4Network] | None = None
    devices: dict | None = None
    when: datetime | None = None

    def __init__(self, hass: HomeAssistant):
        self._hass = hass
        self._devices = {}

    async def _discover(self, addresses: list[str] | str = IP_BROADCAST, wait: bool = False) -> AsyncGenerator[tuple[int, dict[str, str]], None]:
        try:
            transport, protocol = await asyncio.get_running_loop().create_datagram_endpoint(lambda: DiscoveryProtocol(addresses), family = socket.AF_INET, allow_broadcast = True)
            while (r := await asyncio.wait_for(protocol.responses.get(), DISCOVERY_TIMEOUT)) or wait:
                yield r
        except TimeoutError:
            pass
        except Exception as e:
            _LOGGER.debug(f"_discover: {e!r}")
        finally:
            transport.close()

    async def _discover_all(self):
        if Discovery.networks is None:
            _LOGGER.debug(f"_discover_all: network.async_get_adapters")
            Discovery.networks = [n for adapter in await network.async_get_adapters(self._hass) if adapter["enabled"] and adapter["index"] is not None and adapter["ipv4"] for ip in adapter["ipv4"] if (n := IPv4Network(ip["address"] + '/' + str(ip["network_prefix"]), False)) and not n.is_loopback and not n.is_global]
        async for item in self._discover([str(net.broadcast_address) for net in Discovery.networks], True):
            yield item

    async def discover(self, address: str | None = None):
        devices = {}
        async with Discovery.semaphore:
            if Discovery.devices and (datetime.now() - Discovery.when) < DISCOVERY_CACHE:
                devices = Discovery.devices
            if address and not (devices and any([v["ip"] == address for v in devices.values()])):
                devices = {k: v async for k, v in self._discover(address)}
            if not devices:
                Discovery.devices = devices = {k: v async for k, v in self._discover_all()}
                Discovery.when = datetime.now()
        return devices

@callback
def trigger_discovery(hass: HomeAssistant, discovered_devices: dict[int, dict[str, str]]):
    """Trigger config flows for discovered devices."""
    for k, v in discovered_devices.items():
        discovery_flow.async_create_flow(hass, DOMAIN, context = {"source": config_entries.SOURCE_INTEGRATION_DISCOVERY}, data = dict(v, serial = k))
