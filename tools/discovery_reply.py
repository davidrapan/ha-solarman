import socket
import asyncio
import netifaces

DISCOVERY_IP = "0.0.0.0"
DISCOVERY_PORT = 48899
DISCOVERY_MESSAGE = ["WIFIKIT-214028-READ".encode(), "HF-A11ASSISTHREAD".encode()]

ifaces = netifaces.ifaddresses(netifaces.gateways()['default'][2][1])
iface_inet = ifaces[netifaces.AF_INET][0]
iface_link = ifaces[netifaces.AF_LINK][0]

class DiscoveryProtocol:
    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data, addr):
        if data == DISCOVERY_MESSAGE[0]:
            print(f"DiscoveryProtocol: Received {data} from {addr}")
            self.transport.sendto(f"{iface_inet["addr"]},{iface_link["addr"].replace(':', '').upper()},1234567890".encode(), addr)

    def error_received(self, e: OSError):
        print(f"DiscoveryProtocol: {e!r}")

    def connection_lost(self, _):
        print(f"DiscoveryProtocol: Connection closed")

async def main():
    loop = asyncio.get_running_loop()
    transport, _ = await loop.create_datagram_endpoint(DiscoveryProtocol, local_addr = (DISCOVERY_IP, DISCOVERY_PORT), family = socket.AF_INET, allow_broadcast = True)

    try:
        await asyncio.sleep(3600)
    finally:
        transport.close()

if __name__ == '__main__':
    asyncio.run(main())