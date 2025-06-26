import socket
import asyncio
import netifaces

from argparse import ArgumentParser

DISCOVERY_IP = "0.0.0.0"
DISCOVERY_PORT = 48899
DISCOVERY_MESSAGE = ["WIFIKIT-214028-READ".encode(), "HF-A11ASSISTHREAD".encode()]
DISCOVERY_TIMEOUT = 3600

ifaces = netifaces.ifaddresses(netifaces.gateways()['default'][2][1])
iface_inet = ifaces[netifaces.AF_INET][0]["addr"]
iface_link = ifaces[netifaces.AF_LINK][0]["addr"].replace(':', '').upper()

DISCOVERY_MESSAGE_REPLY = f"{iface_inet},{iface_link},1234567890".encode()

class DiscoveryProtocol:
    def connection_made(self, transport: asyncio.DatagramTransport):
        self.transport = transport

    def datagram_received(self, data: bytes, addr: tuple[str, int]):
        if data in DISCOVERY_MESSAGE:
            print(f"DiscoveryProtocol: {data} from {addr}")
            self.transport.sendto(DISCOVERY_MESSAGE_REPLY, addr)

    def error_received(self, e: OSError):
        print(f"DiscoveryProtocol: {e!r}") # Bug on Windows, can't recover from ConnectionResetError: https://github.com/python/cpython/issues/127057

    def connection_lost(self, _: Exception | None):
        print("DiscoveryProtocol: Connection closed")

async def main():
    parser = ArgumentParser("solarman-discovery-reply", description = "Discovery for Solarman Stick Loggers")
    parser.add_argument("--timeout", default = DISCOVERY_TIMEOUT, required = False, type = int, choices = range(3600), help = "Timeout in seconds, an integer in the range 0..3600")

    try:
        transport, _ = await asyncio.get_running_loop().create_datagram_endpoint(DiscoveryProtocol, local_addr = (DISCOVERY_IP, DISCOVERY_PORT), family = socket.AF_INET, allow_broadcast = True)
        await asyncio.sleep(parser.parse_args().timeout)
    finally:
        transport.close()

if __name__ == '__main__':
    asyncio.run(main())
