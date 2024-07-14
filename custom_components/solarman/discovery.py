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
    _port = DISCOVERY_PORT
    _message = DISCOVERY_MESSAGE.encode()

    def __init__(self, hass: HomeAssistant, address = None):
        self._hass = hass
        self._address = address
        self._ip = None
        self._mac = None
        self._serial = None

    async def _discover(self, address = IP_BROADCAST, source = IP_ANY):
        loop = asyncio.get_running_loop()

        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP) as sock:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                sock.setblocking(False)
                sock.settimeout(DISCOVERY_TIMEOUT)

                if source != IP_ANY:
                    sock.bind((source, PORT_ANY))

                await loop.sock_sendto(sock, self._message, (address, self._port))

                while True:
                    try:
                        recv = await loop.sock_recv(sock, DISCOVERY_RECV_MESSAGE_SIZE)
                        data = recv.decode().split(',')
                        if len(data) == 3:
                            self._ip = data[0]
                            self._mac = data[1]
                            self._serial = int(data[2])
                            _LOGGER.debug(f"_discover: [{self._ip}, {self._mac}, {self._serial}]")
                    except (TimeoutError, socket.timeout):
                        break
        except Exception as e:
            _LOGGER.exception(f"_discover: {format_exception(e)}")

    async def _discover_all(self):
        adapters = await network.async_get_adapters(self._hass)

        for adapter in adapters:
            for ipv4 in adapter["ipv4"]:
                net = IPv4Network(ipv4["address"] + '/' + str(ipv4["network_prefix"]), False)
                if net.is_loopback:
                    continue

                _LOGGER.debug(f"_discover_all: Broadcasting on {net.with_prefixlen}")

                await self._discover(str(IPv4Network(net, False).broadcast_address))
                #await self._discover(IP_BROADCAST, ipv4["address"])

                if self._ip is not None:
                    return None

    async def discover(self):
        if self._address:
            await self._discover(self._address)

        attempts_left = ACTION_RETRY_ATTEMPTS
        while self._ip is None and attempts_left > 0:
            attempts_left -= 1

            await self._discover_all()

            if self._ip is None:
                _LOGGER.debug(f"discover: {f'attempts left: {attempts_left}{'' if attempts_left > 0 else ', aborting.'}'}")

    async def get_ip(self):
        if not self._ip:
            await self.discover()
        return self._ip

    async def get_mac(self):
        if not self._mac:
            await self.discover()
        return self._mac

    async def get_serial(self):
        if not self._serial:
            await self.discover()
        return self._serial
