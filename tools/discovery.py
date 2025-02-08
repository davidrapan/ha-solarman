import socket
import asyncio

DISCOVERY_PORT = 48899
DISCOVERY_TIMEOUT = 1
DISCOVERY_MESSAGE = ["WIFIKIT-214028-READ".encode(), "HF-A11ASSISTHREAD".encode()]

class DiscoveryProtocol:
    def __init__(self, addresses):
        self.addresses = addresses
        self.responses = asyncio.Queue()
        self.transport = None

    def connection_made(self, transport):
        self.transport = transport
        print(f"DiscoveryProtocol: Send to {self.addresses}")
        for address in self.addresses:
            self.transport.sendto(DISCOVERY_MESSAGE[0], (address, DISCOVERY_PORT))

    def datagram_received(self, d, _):
        if len(data := d.decode().split(',')) == 3:
            serial = int(data[2])
            self.responses.put_nowait((serial, {"ip": data[0], "mac": data[1]}))
            print(f"DiscoveryProtocol: [{data[0]}, {data[1]}, {serial}]")

    def error_received(self, e):
        print(f"DiscoveryProtocol: Error received: {e}")

    def connection_lost(self, _):
        print(f"DiscoveryProtocol: Connection closed")

async def main():
    loop = asyncio.get_running_loop()
    addresses = ["255.255.255.255"]
    wait = True

    try:
        transport, protocol = await loop.create_datagram_endpoint(lambda: DiscoveryProtocol(addresses), family = socket.AF_INET, allow_broadcast = True),
        r = None
        while r is None or wait:
            r = await asyncio.wait_for(protocol.responses.get(), DISCOVERY_TIMEOUT)
    except TimeoutError:
        pass
    except Exception as e:
        print(f"_discover exception: {e}")
    finally:
        transport.close()

asyncio.run(main())
