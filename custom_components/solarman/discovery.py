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

class InverterDiscovery:
    def __init__(self, hass: HomeAssistant, ip = None, serial = None):
        self._hass = hass
        self._ip = ip
        self._serial = serial
        self._devices = {}

    async def _discover(self, ips = IP_BROADCAST, wait = False, source = IP_ANY) -> dict:
        loop = asyncio.get_running_loop()

        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP) as sock:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                sock.setblocking(False)
                sock.settimeout(DISCOVERY_TIMEOUT)

                if source != IP_ANY:
                    sock.bind((source, PORT_ANY))

                for ip in ensure_list(ips):
                    await loop.sock_sendto(sock, DISCOVERY_MESSAGE, (ip, DISCOVERY_PORT))

                while True:
                    try:
                        data = (await loop.sock_recv(sock, DISCOVERY_RECV_MESSAGE_SIZE)).decode().split(',')
                        if len(data) == 3:
                            serial = int(data[2])
                            yield serial, {"ip": data[0], "mac": data[1]}
                            _LOGGER.debug(f"_discover: [{data[0]}, {data[1]}, {serial}]")
                            if not wait:
                                return
                    except (TimeoutError, socket.timeout):
                        break
        except Exception as e:
            _LOGGER.exception(f"_discover: {format_exception(e)}")

    async def _discover_all(self) -> dict:
        _LOGGER.debug(f"_discover_all")

        adapters = await network.async_get_adapters(self._hass)
        nets = [x for x in [IPv4Network(ipv4["address"] + '/' + str(ipv4["network_prefix"]), False) for adapter in adapters if len(adapter["ipv4"]) > 0 for ipv4 in adapter["ipv4"]] if not x.is_loopback]

        _LOGGER.debug(f"_discover_all: Broadcasting on {nets}")
        async for item in self._discover([str(net.broadcast_address) for net in nets], True):
            yield item

    async def discover(self):
        _LOGGER.debug(f"discover")

        devices = {}

        if self._ip:
            devices = {item[0]: item[1] async for item in self._discover(self._ip)}
            if len(devices) > 0 and self._serial and self._serial != next(iter(devices)):
                devices = {}

        attempts_left = ACTION_ATTEMPTS
        while len(devices) == 0 and attempts_left > 0:
            attempts_left -= 1

            devices = {item[0]: item[1] async for item in self._discover_all()}
            if len(devices) > 0 and self._serial:
                devices = {self._serial: devices[self._serial]} if self._serial in devices else {}

            if len(devices) == 0:
                _LOGGER.debug(f"discover: {f'attempts left: {attempts_left}{'' if attempts_left > 0 else ', aborting.'}'}")

        self._devices = devices

        return self._devices

    async def discover_ip(self):
        if len(self._devices) == 0:
            await self.discover()
            if len(self._devices) == 0:
                return None
        item = next(iter(self._devices))
        return self._devices[item]["ip"]

    async def discover_mac(self):
        if len(self._devices) == 0:
            await self.discover()
            if len(self._devices) == 0:
                return None
        item = next(iter(self._devices))
        return self._devices[item]["mac"]

    async def discover_serial(self):
        if len(self._devices) == 0:
            await self.discover()
            if len(self._devices) == 0:
                return None
        item = next(iter(self._devices))
        return item