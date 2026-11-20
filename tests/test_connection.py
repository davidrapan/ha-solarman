import time
import struct
import asyncio
import pytest

import solarman.pysolarman as ps
from solarman.pysolarman import Solarman, BackoffError, ConnectError
from solarman.pysolarman.umodbus.exceptions import IllegalDataAddressError

class FakeLogger:
    """Minimal Modbus TCP server. `script` is a list of behaviours consumed per received request: ok, silent, garbage, exception (the last one repeats)"""

    def __init__(self, script):
        self.script, self.requests, self.connections = list(script), 0, 0

    async def start(self):
        self.server = await asyncio.start_server(self.handle, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]
        return self

    async def stop(self):
        self.server.close()
        await self.server.wait_closed()

    async def handle(self, reader, writer):
        self.connections += 1
        try:
            while data := await reader.read(1024):
                self.requests += 1
                action = self.script.pop(0) if len(self.script) > 1 else self.script[0]
                tid, _, _, unit, func, _, count = struct.unpack(">HHHBBHH", data[:12])
                if action == "ok":
                    payload = bytes(count * 2)
                    writer.write(struct.pack(">HHHBBB", tid, 0, 3 + len(payload), unit, func, len(payload)) + payload)
                elif action == "garbage":
                    writer.write(b"\x00" * 9)
                elif action == "exception":
                    writer.write(struct.pack(">HHHBBB", tid, 0, 3, unit, func | 0x80, 2))
                await writer.drain()
        except ConnectionError:
            pass
        finally:
            writer.close()

@pytest.fixture(autouse = True)
def fast(monkeypatch):
    monkeypatch.setattr(ps, "CONNECT_BACKOFF", .05)

def run(coro):
    return asyncio.run(coro)

def test_success():
    async def main():
        s = await FakeLogger(["ok"]).start()
        c = Solarman("127.0.0.1", s.port, "modbus_tcp", 0, 1, 1)
        try:
            assert len(await c.execute(3, 0x10, count = 4)) == 4
            assert s.requests == 1 and c._failures == 0
        finally:
            await c.close(); await s.stop()
    run(main())

def test_requests_never_overlap():
    async def main():
        s = await FakeLogger(["ok"]).start()
        c = Solarman("127.0.0.1", s.port, "modbus_tcp", 0, 1, 1)
        try:
            await asyncio.gather(*(c.execute(3, 0x10 * i, count = 2) for i in range(4)))
            assert s.requests == 4 and s.connections == 1
        finally:
            await c.close(); await s.stop()
    run(main())

def test_recoverable_error_is_retried_once():
    async def main():
        s = await FakeLogger(["garbage", "ok"]).start()
        c = Solarman("127.0.0.1", s.port, "modbus_tcp", 0, 1, 1)
        try:
            await c.execute(3, 0, count = 2)
            assert s.requests == 2
        finally:
            await c.close(); await s.stop()
    run(main())

def test_persistent_error_is_bounded_then_backs_off():
    async def main():
        s = await FakeLogger(["garbage"]).start()
        c = Solarman("127.0.0.1", s.port, "modbus_tcp", 0, 1, 1)
        try:
            with pytest.raises(Exception) as e:
                await c.execute(3, 0, count = 2)
            assert not isinstance(e.value, BackoffError) and s.requests == 2
            with pytest.raises(BackoffError): # Fails fast without touching the network
                await c.execute(3, 0, count = 2)
            assert s.requests == 2 and c._failures == 1
        finally:
            await c.close(); await s.stop()
    run(main())

def test_modbus_exception_is_not_retried_and_not_a_failure():
    async def main():
        s = await FakeLogger(["exception"]).start()
        c = Solarman("127.0.0.1", s.port, "modbus_tcp", 0, 1, 1)
        try:
            with pytest.raises(IllegalDataAddressError):
                await c.execute(3, 0, count = 2)
            assert s.requests == 1 and c._failures == 0
        finally:
            await c.close(); await s.stop()
    run(main())

def test_unreachable_logger_does_not_loop():
    async def main():
        s = await FakeLogger(["ok"]).start()
        port = s.port
        await s.stop() # Nothing listens any more: connection refused
        c = Solarman("127.0.0.1", port, "modbus_tcp", 0, 1, 1)
        started = time.monotonic()
        with pytest.raises(ConnectError):
            await c.execute(3, 0, count = 2)
        assert time.monotonic() - started < 3 and not c.connected
        await c.close()
    run(main())

def test_silent_logger_times_out_once_and_backs_off():
    async def main():
        s = await FakeLogger(["silent"]).start()
        c = Solarman("127.0.0.1", s.port, "modbus_tcp", 0, 1, 1)
        try:
            started = time.monotonic()
            with pytest.raises(TimeoutError):
                await c.execute(3, 0, count = 2)
            assert time.monotonic() - started < 7 # timeout * 6
            assert c._failures == 1
            assert s.requests <= 2 and s.connections <= 2 # One reset and resend, no storm
            with pytest.raises(BackoffError):
                await c.execute(3, 0, count = 2)
        finally:
            await c.close(); await s.stop()
    run(main())
