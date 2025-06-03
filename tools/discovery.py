import socket
import asyncio

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

    def datagram_received(self, d: bytes, a: tuple[str, int]):
        if len(data := d.decode().split(',')) == 3:
            serial = int(data[2])
            self.responses.put_nowait((serial, {"ip": data[0], "mac": data[1]}))
            print(f"DiscoveryProtocol: {a}: [{data[0]}, {data[1]}, {serial}]")

    def error_received(self, e: OSError):
        print(f"DiscoveryProtocol: {e!r}")

    def connection_lost(self, _):
        print(f"DiscoveryProtocol: Connection closed")

async def main():
    loop = asyncio.get_running_loop()
    wait = True

    try:
        transport, protocol = await loop.create_datagram_endpoint(lambda: DiscoveryProtocol(DISCOVERY_IP), family = socket.AF_INET, allow_broadcast = True)
        r = None
        while r is None or wait:
            r = await asyncio.wait_for(protocol.responses.get(), DISCOVERY_TIMEOUT)
    except TimeoutError:
        pass
    except Exception as e:
        print(f"Discover: {e!r}")
    finally:
        transport.close()

if __name__ == "__main__":
    asyncio.run(main())
