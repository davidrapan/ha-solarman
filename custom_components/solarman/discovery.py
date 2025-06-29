import socket
import asyncio

from logging import getLogger
from ipaddress import IPv4Network
from contextlib import asynccontextmanager

from homeassistant.helpers import singleton
from homeassistant.core import HomeAssistant
from homeassistant.components import network

from .const import *
from .common import *

_LOGGER = getLogger(__name__)

class DiscoveryProtocol(asyncio.DatagramProtocol):
    def __init__(self, addresses: list[str] | str):
        self.responses: list[asyncio.Queue[tuple[int, dict[str, str]]]] = []
        self.addresses = addresses

    def connection_made(self, transport):
        _LOGGER.debug(f"DiscoveryProtocol: Send to {self.addresses}")
        for address in ensure_list(self.addresses):
            for message in DISCOVERY_MESSAGE:
                transport.sendto(message, (address, DISCOVERY_PORT))

    def datagram_received(self, data, addr):
        if len(d := data.decode().split(',')) == 3 and (s := int(d[2])):
            for r in self.responses:
                r.put_nowait((s, {"ip": d[0], "mac": d[1]}))
            _LOGGER.debug(f"DiscoveryProtocol: [{d[0]}, {d[1]}, {s}] from {addr}")

    def error_received(self, e):
        _LOGGER.debug(f"DiscoveryProtocol: {strepr(e)}")

    def connection_lost(self, _):
        pass

class Discovery:
    def __init__(self):
        self._semaphore = asyncio.Semaphore(1)
        self._transport: asyncio.DatagramTransport | None = None
        self._protocol: DiscoveryProtocol | None = None

    async def init(self, hass: HomeAssistant):
        self._broadcast = [str(n.broadcast_address) for adapter in await network.async_get_adapters(hass) if adapter["enabled"] and adapter["index"] is not None and adapter["ipv4"] for ip in adapter["ipv4"] if (n := IPv4Network(ip["address"] + '/' + str(ip["network_prefix"]), False)) and not n.is_loopback and not n.is_global]
        return self

    @asynccontextmanager
    async def _context(self, address: str | None = None):
        async with self._semaphore:
            if self._transport is None:
                self._transport, self._protocol = await asyncio.get_running_loop().create_datagram_endpoint(lambda: DiscoveryProtocol(address or self._broadcast), family = socket.AF_INET, allow_broadcast = True)
        self._protocol.responses.append(responses := asyncio.Queue())
        try:
            yield responses
        except TimeoutError:
            pass
        except Exception as e:
            _LOGGER.debug(f"_discover: {strepr(e)}")
        finally:
            try:
                self._transport.close()
            except:
                pass
            finally:
                self._transport = None

    async def discover(self, address: str | None = None):
        async with self._context(address) as responses:
            while True:
                k, v = await asyncio.wait_for(responses.get(), DISCOVERY_TIMEOUT)
                yield k, v
                if v["ip"] == address:
                    break

@singleton.singleton(f"{DOMAIN}_discovery")
async def _get_discovery(hass: HomeAssistant):
    return await Discovery().init(hass)

async def discover(hass: HomeAssistant, address: str | None = None):
    return (await _get_discovery(hass)).discover(address)
