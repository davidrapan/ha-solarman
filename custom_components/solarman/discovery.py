from __future__ import annotations

import socket
import logging
from ipaddress import IPv4Network

from homeassistant.core import HomeAssistant
from homeassistant.components import network

_LOGGER = logging.getLogger(__name__)

class InverterDiscovery:
    def __init__(self, hass: HomeAssistant, address = None):
        self._hass = hass
        self._address = address
        self._ip = None
        self._mac = None
        self._serial = None

    def _discover(self, address = "<broadcast>"):
        request = "WIFIKIT-214028-READ"
        endpoint = (address, 48899)

        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP) as sock:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                sock.settimeout(1.0)
                sock.sendto(request.encode(), endpoint)

                while True:
                    try:
                        recv = sock.recv(1024)
                        data = recv.decode().split(',')
                        if len(data) == 3:
                            self._ip = data[0]
                            self._mac = data[1]
                            self._serial = int(data[2])
                            _LOGGER.debug(f"_discover: [{self._ip}, {self._mac}, {self._serial}]")
                    except socket.timout:
                        break
        except:
            return None

    async def _discover_all(self):
        adapters = await network.async_get_adapters(self._hass)

        for adapter in adapters:
            for ipv4 in adapter["ipv4"]:
                net = IPv4Network(ipv4["address"] + '/' + str(ipv4["network_prefix"]), False)
                if net.is_loopback:
                    continue

                _LOGGER.debug(f"_discover_all: Broadcasting on {(net.with_prefixlen)}")

                self._discover(str(IPv4Network(net, False).broadcast_address))

                if self._ip is not None:
                    return None

    async def discover(self):
        if self._address:
            self._discover(self._address)

        c = 0
        while self._ip is None and c < 4:
            c += 1
            await self._discover_all()
            if self._ip is None:
                _LOGGER.debug(f"discover: Failed. (Attempt: {c})")

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