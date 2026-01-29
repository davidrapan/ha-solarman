import time
import types
import struct
import logging
import asyncio

from functools import wraps
from random import randrange
from logging import getLogger
from multiprocessing import Event

from .umodbus.functions import FUNCTION_CODES
from .umodbus.exceptions import error_code_to_exception_map
from .umodbus.client.serial.redundancy_check import get_crc
from .umodbus.client.serial import rtu
from .umodbus.client import tcp

from ..common import retry, throttle, create_task, format

_LOGGER = getLogger(__name__)

PROTOCOL = types.SimpleNamespace()
PROTOCOL.CONTROL_CODE = types.SimpleNamespace()
PROTOCOL.CONTROL_CODE.HANDSHAKE = 0x41
PROTOCOL.CONTROL_CODE.DATA = 0x42
PROTOCOL.CONTROL_CODE.INFO = 0x43
PROTOCOL.CONTROL_CODE.REQUEST = 0x45
PROTOCOL.CONTROL_CODE.HEARTBEAT = 0x47
PROTOCOL.CONTROL_CODE.REPORT = 0x48
PROTOCOL.CONTROL_CODE_SUFFIX = bytes.fromhex("10")
PROTOCOL.CONTROL_CODES = PROTOCOL.CONTROL_CODE.__dict__.values()
PROTOCOL.FRAME_TYPE = bytes.fromhex("02")
PROTOCOL.STATUS = bytes.fromhex("01")
PROTOCOL.PLACEHOLDER1 = bytes.fromhex("00")
PROTOCOL.PLACEHOLDER2 = bytes.fromhex("0000") # sensor type and double crc
PROTOCOL.PLACEHOLDER3 = bytes.fromhex("00000000") # offset time
PROTOCOL.PLACEHOLDER4 = bytes.fromhex("000000000000000000000000") # delivery|poweron|offset time
PROTOCOL.START = bytes.fromhex("A5")
PROTOCOL.END = bytes.fromhex("15")

def log_call(prefix: str):
    def decorator(f):
        @wraps(f)
        async def wrapper(*args, **kwargs):
            _LOGGER.debug(f"[{args[0].host}] {prefix}{f': {format(args[1])}' if len(args) > 1 else ''}")
            return await f(*args, **kwargs)
        return wrapper
    return decorator

def log_return(prefix: str):
    def decorator(f):
        @wraps(f)
        async def wrapper(*args, **kwargs):
            r = await f(*args, **kwargs)
            _LOGGER.debug(f"[{args[0].host}] {prefix}: {format(r)}")
            return r
        return wrapper
    return decorator

class FrameError(Exception):
    """Frame Validation Error"""

class Solarman:
    def __init__(self, host: str, port: int | str, transport: str, serial: int, slave: int, timeout: int):
        self.host = host
        self.port = port
        self.transport = transport
        self.serial = serial
        self.slave = slave
        self.timeout = timeout

        self._keeper: asyncio.Task | None = None
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._lock = asyncio.Lock()
        self._data_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize = 1)
        self._data_event = Event()
        self._last_frame: bytes | None = None

    @staticmethod
    def _get_response_code(code: int):
        return code - 0x30

    @staticmethod
    def _calculate_checksum(frame: bytes):
        checksum = 0
        for d in frame:
            checksum += d & 0xFF
        return int(checksum & 0xFF)

    @property
    def serial(self):
        return self._serial

    @serial.setter
    def serial(self, value: int | bytes):
        match value:
            case int():
                self._serial = value
                self.serial_bytes = struct.pack("<I", value) if 2147483648 <= value <= 4294967295 else PROTOCOL.PLACEHOLDER3
            case bytes():
                self._serial = int.from_bytes(value, "little")
                self.serial_bytes = value

    @property
    def transport(self):
        return self._transport

    @transport.setter
    def transport(self, value: str):
        self._transport = value
        if value == "tcp":
            self._get_response = self._parse_adu_from_sol_response
            self._handle_frame = self._handle_protocol_frame
        else:
            self._get_response = self._parse_adu_from_tcp_response if not value.endswith("rtu") else self._parse_adu_from_rtu_response
            self._handle_frame = None

    @property
    def connected(self):
        return self._keeper is not None and not self._keeper.done()

    @property
    def sequence_number(self):
        self._sequence_number = ((self._sequence_number + 1) & 0xFF) if hasattr(self, "_sequence_number") else randrange(0x01, 0xFF)
        return self._sequence_number

    def _protocol_header(self, length: int, control: int, seq: bytes):
        return bytearray(PROTOCOL.START
            + struct.pack("<H", length)
            + PROTOCOL.CONTROL_CODE_SUFFIX
            + struct.pack("<B", control)
            + seq
            + self.serial_bytes)

    def _protocol_trailer(self, frame: bytes):
        return bytearray(struct.pack("<B", self._calculate_checksum(frame[1:])) + PROTOCOL.END)

    def _received_frame_is_valid(self, frame: bytes):
        if not frame.startswith(PROTOCOL.START):
            _LOGGER.debug(f"[{self.host}] PROTOCOL_MISMATCH: {frame.hex(" ")}")
            return False
        if frame[5] != self._sequence_number:
            if frame[4] == PROTOCOL.CONTROL_CODE.REQUEST and len(frame) > 6 and (f := int.from_bytes(frame[5:6], "big") == len(frame[6:])) and (int.from_bytes(frame[8:9], "big") == len(frame[9:]) if len(frame) > 9 else f):
                _LOGGER.debug(f"[{self.host}] TCP_DETECTED: {frame.hex(" ")}")
                self.transport = "modbus_tcp"
                return True
            _LOGGER.debug(f"[{self.host}] SEQ_MISMATCH: {frame.hex(" ")}")
            return False
        if not frame.endswith(PROTOCOL.END):
            _LOGGER.debug(f"[{self.host}] PROTOCOL_MISMATCH: {frame.hex(" ")}")
            return False
        return True

    def _received_frame_response(self, frame: bytes):
        do_continue = True
        response_frame = None
        if frame[4] != PROTOCOL.CONTROL_CODE.REQUEST and frame[4] in PROTOCOL.CONTROL_CODES:
            do_continue = False
            # Maybe do_continue = True for CONTROL_CODE.DATA|INFO|REPORT and thus process packets in the future?
            control_name = [i for i in PROTOCOL.CONTROL_CODE.__dict__ if PROTOCOL.CONTROL_CODE.__dict__[i] == frame[4]][0]
            _LOGGER.debug(f"[{self.host}] PROTOCOL_{control_name} RECV: {frame.hex(" ")}")
            response_frame = self._protocol_header(10, self._get_response_code(frame[4]), frame[5:7]) + bytearray(PROTOCOL.PLACEHOLDER1 # Frame Type
                + PROTOCOL.STATUS
                + struct.pack("<I", int(time.time()))
                + PROTOCOL.PLACEHOLDER3) # Offset?
            response_frame[5] = (response_frame[5] + 1) & 0xFF
            response_frame += self._protocol_trailer(response_frame)
            _LOGGER.debug(f"[{self.host}] PROTOCOL_{control_name} SENT: {response_frame.hex(" ")}")
        return do_continue, response_frame

    async def _write(self, data: bytes):
        try:
            self._writer.write(data)
            await self._writer.drain()
        except AttributeError as e:
            raise ConnectionError("Connection is closed") from e
        except OSError as e:
            raise TimeoutError("Peer is unreachable") from e
        except Exception as e:
            raise e

    async def _handle_protocol_frame(self, frame):
        if (do_continue := self._received_frame_is_valid(frame)):
            do_continue, response_frame = self._received_frame_response(frame)
            if response_frame is not None:
                await self._write(response_frame)
        return do_continue

    async def _keeper_loop(self):
        while True:
            try:
                data = await self._reader.read(1024)
            except ConnectionResetError:
                _LOGGER.debug(f"[{self.host}] Connection is reset by the peer. Will try to restart the connection")
                break
            if data == b"":
                _LOGGER.debug(f"[{self.host}] Connection closed. Will try to restart the connection")
                break
            if self._handle_frame is not None and not await self._handle_frame(data):
                # Skip...
                continue
            if not self._data_event.is_set():
                _LOGGER.debug(f"[{self.host}] Data received too late")
                continue
            if not self._data_queue.empty():
                _ = self._data_queue.get_nowait()
            self._data_queue.put_nowait(data)
            self._data_event.clear()
        self._keeper = create_task(self._open_connection())

    @throttle(0.2)
    async def _open_connection(self) -> None:
        try:
            self._reader, self._writer = await asyncio.wait_for(asyncio.open_connection(self.host, self.port), self.timeout)
            self._keeper = create_task(self._keeper_loop())
            if self._data_event.is_set():
                _LOGGER.debug(f"[{self.host}] Successful reconnection! Data expected. Will retry the last request")
                await self._write(self._last_frame)
            else:
                _LOGGER.debug(f"[{self.host}] Successful connection!")
        except Exception as e:
            if self._last_frame is None:
                raise ConnectionError("Cannot open connection") from e
            await self._open_connection()

    async def _close(self) -> None:
        if self._writer:
            try:
                await self._write(b"")
            except (ConnectionError, TimeoutError) as e:
                _LOGGER.debug(f"[{self.host}] {e!r} can be during closing ignored")

            try:
                self._writer.close()
                await self._writer.wait_closed()
            except (AttributeError, OSError) as e: # OSError happens when is host unreachable
                _LOGGER.debug(f"[{self.host}] {e!r} can be during closing ignored")

            self._writer = None

        self._reader = None

    @throttle(0.1)
    @log_call("SENT")
    @log_return("RECV")
    async def _send_receive_frame(self, frame: bytes):
        if not self._writer:
            if not self.connected:
                self._keeper = create_task(self._open_connection())
            await self._keeper

        self._data_event.set()
        self._last_frame = frame

        try:
            await self._write(frame)
            while True:
                try:
                    return await asyncio.wait_for(self._data_queue.get(), self.timeout * 3 - 1)
                except TimeoutError:
                    await self._close()
        finally:
            self._data_event.clear()

    async def _parse_adu_from_sol_response(self, code: int, address: int, **kwargs) -> list[int]:
        async def _get_sol_response(frame: bytes) -> bytes:
            request_frame = self._protocol_header(15 + len(frame),
                PROTOCOL.CONTROL_CODE.REQUEST,
                struct.pack("<H", self.sequence_number)
            ) + bytearray(PROTOCOL.FRAME_TYPE
                + PROTOCOL.PLACEHOLDER2 # sensor type
                + PROTOCOL.PLACEHOLDER4 # delivery|poweron|offset time
                + frame)
            return await self._send_receive_frame(request_frame + self._protocol_trailer(request_frame))
        req = rtu.function_code_to_function_map[code](self.slave, address, **kwargs)
        res = await _get_sol_response(req)
        if self.serial_bytes == PROTOCOL.PLACEHOLDER3 and self.transport == "tcp":
            self.serial = res[7:11]
            _LOGGER.debug(f"[{self.host}] SERIAL_SET: {self.serial}")
            res = await _get_sol_response(req)
        if res[4] != self._get_response_code(PROTOCOL.CONTROL_CODE.REQUEST):
            raise FrameError("Invalid control code")
        if res[5] != self._sequence_number:
            raise FrameError("Invalid sequence number")
        if res[11:12] != PROTOCOL.FRAME_TYPE:
            _LOGGER.debug(f"[{self.host}] UNEXPECTED_FRAME_TYPE: {int.from_bytes(res[11:12])}")
        if res[-2] != self._calculate_checksum(res[1:-2]):
            raise FrameError("Invalid checksum")
        res = res[25:-2]
        if len(res) < 5: # Short version of modbus exception (undocumented)
            if len (res) > 0 and (modbusError := error_code_to_exception_map.get(res[0])):
                raise modbusError()
            raise FrameError("Invalid modbus frame")
        if res.endswith(PROTOCOL.PLACEHOLDER2) and get_crc(res[:-4]) == res[-4:-2]: # Double CRC (XXXX0000) correction
            res = res[:-2]
        return rtu.parse_response_adu(res, req)

    async def _parse_adu_from_rtu_response(self, code: int, address: int, **kwargs) -> list[int]:
        req = rtu.function_code_to_function_map[code](self.slave, address, **kwargs)
        return rtu.parse_response_adu(await self._send_receive_frame(req), req)

    async def _parse_adu_from_tcp_response(self, code: int, address: int, **kwargs) -> list[int]:
        req = tcp.function_code_to_function_map[code](self.slave, address, **kwargs)
        res = await self._send_receive_frame(req)
        if 8 <= len(res) <= 10: # Incomplete response correction
            res = res[:5] + b'\x06' + res[6:] + (req[len(res):10] if len(req) > 12 else (b'\x00' * (10 - len(res)))) + b'\x00\x01'
        return tcp.parse_response_adu(res, req)

    @retry()
    async def get_response(self, code: int, address: int, **kwargs):
        return await self._get_response(code, address, **kwargs)

    @log_return("DATA")
    async def execute(self, code: int, address: int, **kwargs):
        if code not in FUNCTION_CODES:
            raise Exception(f"Invalid modbus function code {code:02}")

        async with asyncio.timeout(self.timeout * 6):
            async with self._lock:
                return await self.get_response(code, address, **kwargs)

    @log_call("Closing connection")
    async def close(self):
        async with self._lock:
            if self.connected:
                self._keeper.cancel()

            self._keeper = None

            await self._close()
