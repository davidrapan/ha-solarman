import socket
import asyncio

from argparse import ArgumentParser

DISCOVERY_IP = "255.255.255.255"
DISCOVERY_PORT = 48899
DISCOVERY_MESSAGE = ["WIFIKIT-214028-READ".encode(), "HF-A11ASSISTHREAD".encode()]
DISCOVERY_TIMEOUT = 1

class DiscoveryProtocol:
    def __init__(self, addresses: list[str] | str):
        self.addresses = addresses
        self.responses: asyncio.Queue = asyncio.Queue()
        self.transport: asyncio.DatagramTransport | None = None

    def connection_made(self, transport: asyncio.DatagramTransport):
        self.transport = transport
        print(f"DiscoveryProtocol: Send to {self.addresses}")
        for address in self.addresses if isinstance(self.addresses, list) else [self.addresses]:
            for message in DISCOVERY_MESSAGE:
                self.transport.sendto(message, (address, DISCOVERY_PORT))

    def datagram_received(self, data: bytes, addr: tuple[str, int]):
        if len(d := data.decode().split(',')) == 3 and (s := int(d[2])):
            self.responses.put_nowait((s, {"ip": d[0], "mac": d[1]}))
            print(f"DiscoveryProtocol: [{d[0]}, {d[1]}, {s}] from {addr}")

    def error_received(self, e: OSError):
        print(f"DiscoveryProtocol: {e!r}")

    def connection_lost(self, _: Exception | None):
        print(f"DiscoveryProtocol: Connection closed")

async def main():
    parser = ArgumentParser(
        "solarman-discovery", description = "Discovery for Solarman Stick Loggers"
    )
    parser.add_argument("--address", default = DISCOVERY_IP, required = False, help = "Network IPv4 address", type = str)
    parser.add_argument("--wait", default = True, required = False, help = "Gather responses until timeout", type = bool)
    args = parser.parse_args()

    try:
        transport, protocol = await asyncio.get_running_loop().create_datagram_endpoint(lambda: DiscoveryProtocol(args.address), family = socket.AF_INET, allow_broadcast = True)
        r = None
        while r is None or args.wait:
            r = await asyncio.wait_for(protocol.responses.get(), DISCOVERY_TIMEOUT)
    except TimeoutError:
        pass
    except Exception as e:
        print(repr(e))
    finally:
        transport.close()

if __name__ == "__main__":
    asyncio.run(main())
