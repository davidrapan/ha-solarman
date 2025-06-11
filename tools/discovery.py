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
        self.responses = asyncio.Queue()

    def connection_made(self, transport: asyncio.DatagramTransport):
        print(f"DiscoveryProtocol: Send to {self.addresses}")
        for address in self.addresses if isinstance(self.addresses, list) else [self.addresses]:
            for message in DISCOVERY_MESSAGE:
                transport.sendto(message, (address, DISCOVERY_PORT))

    def datagram_received(self, data: bytes, addr: tuple[str, int]):
        if len(d := data.decode().split(',')) == 3 and (s := int(d[2])):
            self.responses.put_nowait((s, {"ip": d[0], "mac": d[1]}))
            print(f"DiscoveryProtocol: [{d[0]}, {d[1]}, {s}] from {addr}")

    def error_received(self, e: OSError):
        print(f"DiscoveryProtocol: {e!r}")

    def connection_lost(self, _: Exception | None):
        print("DiscoveryProtocol: Connection closed")

async def main():
    parser = ArgumentParser("solarman-discovery", description = "Discovery for Solarman Stick Loggers")
    parser.add_argument("--address", default = DISCOVERY_IP, required = False, type = str, help = "Network IPv4 address")
    parser.add_argument("--timeout", default = DISCOVERY_TIMEOUT, required = False, type = int, choices = range(10), help = "Timeout in seconds, an integer in the range 0..9")
    parser.add_argument("--wait", default = True, required = False, type = bool, help = "Wait for multiple responses")
    args = parser.parse_args()

    try:
        transport, protocol = await asyncio.get_running_loop().create_datagram_endpoint(lambda: DiscoveryProtocol(args.address), family = socket.AF_INET, allow_broadcast = True)
        while await asyncio.wait_for(protocol.responses.get(), args.timeout) is None or args.wait:
            pass
    except TimeoutError:
        pass
    except Exception as e:
        print(repr(e))
    finally:
        transport.close()

if __name__ == "__main__":
    asyncio.run(main())
