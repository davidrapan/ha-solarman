import socket
import netifaces

if __name__ == '__main__':

    ifaces = netifaces.ifaddresses(netifaces.gateways()['default'][2][1])
    iface_inet = ifaces[netifaces.AF_INET][0]
    iface_link = ifaces[netifaces.AF_LINK][0]

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.settimeout(1)
        s.bind(('', 48899))

        while True:
            try:
                m = s.recvfrom(1024)
                d = m[0].decode()
                if d == "WIFIKIT-214028-READ":
                    print(f"{m[0]} from {m[1]}")
                    data = f"{iface_inet["addr"]},{iface_link["addr"].replace(':', '').upper()},1234567890"
                    s.sendto(data.encode(), m[1])
            except (TimeoutError, socket.timeout):
                continue