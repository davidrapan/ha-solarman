import time
import types
import errno
import struct
import logging
import asyncio

from multiprocessing import synchronize
from multiprocessing import Event
from random import randrange

from .umodbus.exceptions import error_code_to_exception_map
from .umodbus.client.serial.redundancy_check import get_crc
from .umodbus.client.serial import rtu
from .umodbus.client import tcp

_LOGGER = logging.getLogger(__name__)

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

class FrameError(Exception):
    """Frame Validation Error"""

class NoSocketAvailableError(Exception):
    """No Socket Available Error"""

class Solarman:
    def __init__(self, address, port, transport, serial, slave, timeout):
        self.address = address
        self.port = port
        self.transport = transport
        self.serial = serial
        self.slave = slave
        self.timeout = timeout

        self.open_task: asyncio.Task = None
        self.reader_task: asyncio.Task = None
        self.reader: asyncio.StreamReader = None
        self.writer: asyncio.StreamWriter = None
        self.data_queue = asyncio.Queue(maxsize = 1)
        self.data_wanted_ev: synchronize.Event = Event()

    @staticmethod
    def _get_response_code(code: int) -> int:
        return code - 0x30

    @staticmethod
    def _calculate_checksum(data: bytes) -> int:
        checksum = 0
        for d in data:
            checksum += d & 0xFF
        return int(checksum & 0xFF)

    @property
    def serial(self) -> int:
        return self._serial

    @serial.setter
    def serial(self, value: int | bytes) -> None:
        if isinstance(value, int):
            self._serial = value
            self.serial_bytes = struct.pack("<I", value) if value > 0 else PROTOCOL.PLACEHOLDER3
        else:
            self._serial = int.from_bytes(value, "little")
            self.serial_bytes = value

    @property
    def transport(self) -> str:
        return self._transport

    @transport.setter
    def transport(self, value: str) -> None:
        self._transport = value
        if value == "tcp":
            self._lookup = rtu.function_code_to_function_map
            self._get_response = self._parse_adu_from_rtu_response
            self._handle_frame = self._handle_protocol_frame
        else:
            self._lookup = tcp.function_code_to_function_map
            self._get_response = self._parse_adu_from_tcp_response
            self._handle_frame = None

    @property
    def connected(self):
        return self.reader_task and not self.reader_task.done()

    @property
    def sequence_number(self) -> int:
        self._sequence_number = ((self._sequence_number + 1) & 0xFF) if hasattr(self, "_sequence_number") else randrange(0x01, 0xFF)
        return self._sequence_number

    def _protocol_header(self, length: int, control: int, seq: bytes) -> bytearray:
        return bytearray(PROTOCOL.START
            + struct.pack("<H", length)
            + PROTOCOL.CONTROL_CODE_SUFFIX
            + struct.pack("<B", control)
            + seq
            + self.serial_bytes)

    def _protocol_trailer(self, data: bytes) -> bytearray:
        return bytearray(struct.pack("<B", self._calculate_checksum(data[1:])) + PROTOCOL.END)

    def _received_frame_is_valid(self, frame: bytes) -> bool:
        if not frame.startswith(PROTOCOL.START):
            _LOGGER.debug(f"[{self.address}] PROTOCOL_MISMATCH: {frame.hex(" ")}")
            return False
        if frame[5] != self._sequence_number:
            if frame[4] == PROTOCOL.CONTROL_CODE.REQUEST and len(frame) > 6 and (f := int.from_bytes(frame[5:6], "big") == len(frame[6:])) and (int.from_bytes(frame[8:9], "big") == len(frame[9:]) if len(frame) > 9 else f):
                _LOGGER.debug(f"[{self.address}] TCP_DETECTED: %s", self.address, frame.hex(" "))
                self.transport = "modbus_tcp"
                return True
            _LOGGER.debug(f"[{self.address}] SEQ_MISMATCH: {frame.hex(" ")}")
            return False
        if not frame.endswith(PROTOCOL.END):
            _LOGGER.debug(f"[{self.address}] PROTOCOL_MISMATCH: {frame.hex(" ")}")
            return False
        return True

    def _received_frame_response(self, frame: bytes) -> tuple[bool, bytearray]:
        do_continue = True
        response_frame = None
        if frame[4] != PROTOCOL.CONTROL_CODE.REQUEST and frame[4] in PROTOCOL.CONTROL_CODES:
            do_continue = False
            # Maybe do_continue = True for CONTROL_CODE.DATA|INFO|REPORT and thus process packets in the future?
            control_name = [i for i in PROTOCOL.CONTROL_CODE.__dict__ if PROTOCOL.CONTROL_CODE.__dict__[i] == frame[4]][0]
            _LOGGER.debug(f"[{self.address}] PROTOCOL_{control_name}: {frame.hex(" ")}")
            response_frame = self._protocol_header(10, self._get_response_code(frame[4]), frame[5:7]) + bytearray(PROTOCOL.PLACEHOLDER1 # Frame Type
                + PROTOCOL.STATUS
                + struct.pack("<I", int(time.time()))
                + PROTOCOL.PLACEHOLDER3) # Offset?
            response_frame[5] = (response_frame[5] + 1) & 0xFF
            response_frame += self._protocol_trailer(response_frame)
            _LOGGER.debug(f"[{self.address}] PROTOCOL_{control_name} RESP: {response_frame.hex(" ")}")
        return do_continue, response_frame

    async def _write(self, data: bytes) -> None:
        try:
            self.writer.write(data)
            await self.writer.drain()
        except Exception as e:
            match e:
                case AttributeError():
                    raise NoSocketAvailableError("Connection already closed") from e
                case OSError() if e.errno == errno.EHOSTUNREACH:
                    raise TimeoutError from e
            _LOGGER.exception(f"[{self.address}] Write error: {e!r}")

    async def _handle_protocol_frame(self, frame):
        if (do_continue := self._received_frame_is_valid(frame)):
            do_continue, response_frame = self._received_frame_response(frame)
            if response_frame is not None:
                await self._write(response_frame)
        return do_continue

    async def _conn_keeper(self) -> None:
        while True:
            try:
                data = await self.reader.read(1024)
            except ConnectionResetError:
                _LOGGER.debug(f"[{self.address}] Connection is reset by the peer. Will try to restart the connection")
                break
            if data == b"":
                _LOGGER.debug(f"[{self.address}] Connection closed by the remote. Will try to restart the connection")
                break
            if self._handle_frame is not None and not await self._handle_frame(data):
                # Skip...
                continue
            if not self.data_wanted_ev.is_set():
                _LOGGER.debug(f"[{self.address}] Data received but nobody waits for it... Discarded")
                continue
            if not self.data_queue.empty():
                _ = self.data_queue.get_nowait()
            self.data_queue.put_nowait(data)
            self.data_wanted_ev.clear()
        self.reader_task = None
        self.reader = None
        self.writer = None
        self._open()

    async def _open_connection(self) -> None:
        try:
            if self.reader_task:
                self.reader_task.cancel()
            self.reader, self.writer = await asyncio.wait_for(asyncio.open_connection(self.address, self.port), self.timeout)
            self.reader_task = asyncio.get_running_loop().create_task(self._conn_keeper(), name = "ConnKeeper")
            if self.data_wanted_ev.is_set():
                _LOGGER.debug(f"[{self.address}] Successful reconnection! Data expected. Will retry the last request")
                await self._write(self._last_frame)
            else:
                _LOGGER.debug(f"[{self.address}] Successful connection!")
            self.open_task = None
        except Exception as e:
            if self.data_wanted_ev.is_set():
                _LOGGER.debug(f"[{self.address}] {e!r}")
                await self._open_connection()
            else:
                raise NoSocketAvailableError(f"[{self.address}] Cannot open connection") from e

    def _open(self):
        if not self.connected:
            if self.open_task:
                self.open_task.cancel()
            self.open_task = asyncio.get_running_loop().create_task(self._open_connection(), name = "OpenKeeper")

    async def _close(self) -> None:
        if self.writer:
            try:
                await self._write(b"")
            except (NoSocketAvailableError, TimeoutError, ConnectionResetError) as e:
                _LOGGER.debug(f"[{self.address}] {e} can be during closing ignored")
            finally:
                try:
                    self.writer.close()
                    await self.writer.wait_closed()
                except (AttributeError, OSError) as e: # OSError happens when is host unreachable
                    _LOGGER.debug(f"[{self.address}] {e} can be during closing ignored")
                self.writer = None

    async def _send_receive_frame(self, frame: bytes) -> bytes:
        await self.open()
        _LOGGER.debug(f"[{self.address}] SENT: {frame.hex(" ")}")
        self.data_wanted_ev.set()
        self._last_frame = frame
        try:
            await self._write(frame)
            while True:
                try:
                    response_frame = await asyncio.wait_for(self.data_queue.get(), self.timeout)
                    _LOGGER.debug(f"[{self.address}] RECD: {response_frame.hex(" ")}")
                    return response_frame
                except TimeoutError:
                    _LOGGER.debug(f"[{self.address}] Peer not responding. Closing connection")
                    await self._close()
                    continue
        finally:
            self.data_wanted_ev.clear()

    async def _parse_adu_from_rtu_response(self, frame: bytes) -> tuple[int, int, bytes]:
        async def _get_rtu_response(frame: bytes) -> bytes:
            request_frame = self._protocol_header(15 + len(frame),
                PROTOCOL.CONTROL_CODE.REQUEST,
                struct.pack("<H", self.sequence_number)
            ) + bytearray(PROTOCOL.FRAME_TYPE
                + PROTOCOL.PLACEHOLDER2 # sensor type
                + PROTOCOL.PLACEHOLDER4 # delivery|poweron|offset time
                + frame)
            return await self._send_receive_frame(request_frame + self._protocol_trailer(request_frame))
        response_frame = await _get_rtu_response(frame)
        if self.serial_bytes == PROTOCOL.PLACEHOLDER3:
            self.serial = response_frame[7:11]
            _LOGGER.debug(f"[{self.address}] SERIAL_SET: {response_frame.hex(" ")}")
            response_frame = await _get_rtu_response(frame)
        if response_frame[4] != self._get_response_code(PROTOCOL.CONTROL_CODE.REQUEST):
            raise FrameError("Incorrect control code")
        if response_frame[5] != self._sequence_number:
            raise FrameError("Invalid sequence number")
        if response_frame[11:12] != PROTOCOL.FRAME_TYPE:
            raise FrameError("Invalid frame type")
        if response_frame[-2] != self._calculate_checksum(response_frame[1:-2]):
            raise FrameError("Invalid checksum")
        adu = response_frame[25:-2]
        if len(adu) < 5: # Short version of modbus exception (undocumented)
            if len (adu) > 0 and (err := error_code_to_exception_map.get(adu[0])):
                raise FrameError(f"Modbus exception: {err.__name__}")
            raise FrameError(f"Invalid modbus frame")
        if adu.endswith(PROTOCOL.PLACEHOLDER2) and get_crc(adu[:-4]) == adu[-4:-2]: # Double CRC (XXXX0000) correction
            adu = adu[:-2]
        return rtu.parse_response_adu(adu, frame)

    async def _parse_adu_from_tcp_response(self, frame: bytes) -> tuple[int, int, bytes]:
        adu = await self._send_receive_frame(frame)
        if 8 <= len(adu) <= 10: # Incomplete response frame correction
            adu = adu[:5] + b'\x06' + adu[6:] + (frame[len(adu):10] if len(frame) > 12 else (b'\x00' * (10 - len(adu)))) + b'\x00\x01'
        return tcp.parse_response_adu(adu, frame)

    async def execute(self, code, **kwargs):
        if (func := self._lookup.get(code)) is not None:
            data = await self._get_response(func(self.slave, **kwargs))
            _LOGGER.debug(f"[{self.address}] Data: {data}")
            return data
        raise Exception(f"[{self.address}] Used invalid modbus function code %d", code)

    async def open(self):
        self._open()
        if self.open_task is not None:
            await self.open_task

    async def close(self) -> None:
        try:
            if self.open_task:
                self.open_task.cancel()
            if self.reader_task:
                self.reader_task.cancel()
            await self._close()
        finally:
            self.open_task = None
            self.reader_task = None
            self.reader = None
