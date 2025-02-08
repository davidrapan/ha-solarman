from __future__ import annotations

import socket
import logging
import asyncio

from ipaddress import IPv4Network

from homeassistant.core import HomeAssistant
from homeassistant.components import network

from .const import *
from .common import *

_LOGGER = logging.getLogger(__name__)

class DiscoveryProtocol:
    def __init__(self, addresses):
        self.addresses = addresses
        self.responses = asyncio.Queue()
        self.transport = None

    def connection_made(self, transport):
        self.transport = transport
        _LOGGER.debug(f"DiscoveryProtocol: Send to {self.addresses}")
        for address in ensure_list(self.addresses):
            self.transport.sendto(DISCOVERY_MESSAGE[0], (address, DISCOVERY_PORT))

    def datagram_received(self, d, _):
        if len(data := d.decode().split(',')) == 3:
            serial = int(data[2])
            self.responses.put_nowait((serial, {"ip": data[0], "mac": data[1]}))
            _LOGGER.debug(f"DiscoveryProtocol: [{data[0]}, {data[1]}, {serial}]")

    def error_received(self, e):
        _LOGGER.debug(f"DiscoveryProtocol: Error received:", e)

    def connection_lost(self, _):
        _LOGGER.debug(f"DiscoveryProtocol: Connection closed")

class Discovery:
    networks = None

    def __init__(self, hass: HomeAssistant, ip = None, serial = None):
        self._hass = hass
        self._ip = ip
        self._serial = serial
        self._devices = {}

    async def _discover(self, ips = IP_BROADCAST, wait = False):
        loop = asyncio.get_running_loop()

        try:
            transport, protocol = await loop.create_datagram_endpoint(lambda: DiscoveryProtocol(ips), family = socket.AF_INET, allow_broadcast = True)
            try:
                while (response := await asyncio.wait_for(protocol.responses.get(), DISCOVERY_TIMEOUT)) is not None:
                    yield response
                    if not wait:
                        return
            except TimeoutError:
                pass
            finally:
                transport.close()
        except Exception as e:
            _LOGGER.debug(f"_discover exception: {format_exception(e)}")

    async def _discover_all(self):
        if not self._hass:
            return

        if Discovery.networks is None:
            Discovery.networks = [x for x in [IPv4Network(ipv4["address"] + '/' + str(ipv4["network_prefix"]), False) for adapter in await network.async_get_adapters(self._hass) if len(adapter["ipv4"]) > 0 for ipv4 in adapter["ipv4"]] if not x.is_loopback]

        _LOGGER.debug(f"_discover_all: Broadcasting on {Discovery.networks}")
        async for item in self._discover([str(net.broadcast_address) for net in Discovery.networks], True):
            yield item

    async def discover(self, ping_only = False):
        self._devices = {}

        if self._ip:
            _LOGGER.debug(f"_discover: Broadcasting on {self._ip}")
            self._devices = {item[0]: item[1] async for item in self._discover(self._ip)}
            if len(self._devices) > 0 and not self._serial in self._devices:
                self._devices = {}
            if ping_only:
                return self._devices

        attempts_left = 1
        while len(self._devices) == 0 and attempts_left > 0:
            attempts_left -= 1

            self._devices = {item[0]: item[1] async for item in self._discover_all()}

            if len(self._devices) == 0:
                _LOGGER.debug(f"discover: {f'attempts left: {attempts_left}{'' if attempts_left > 0 else ', aborting.'}'}")

        return self._devices
