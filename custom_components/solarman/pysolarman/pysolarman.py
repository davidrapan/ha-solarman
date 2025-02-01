import time
import types
import errno
import struct
import logging
import asyncio

from random import randrange
from multiprocessing import Event

from umodbus.client import tcp
from umodbus.client.serial import rtu
from umodbus.client.serial.redundancy_check import get_crc
from umodbus.exceptions import ModbusError, error_code_to_exception_map

_LOGGER = logging.getLogger(__name__)

PROTOCOL = types.SimpleNamespace()
PROTOCOL.START = bytes.fromhex("A5")
PROTOCOL.CONTROL_CODE_SUFFIX = bytes.fromhex("10")
PROTOCOL.FRAME_TYPE = bytes.fromhex("02")
PROTOCOL.PLACEHOLDER1 = bytes.fromhex("0000")
PROTOCOL.PLACEHOLDER2 = bytes.fromhex("00000000")
PROTOCOL.END = bytes.fromhex("15")

CONTROL_CODE = types.SimpleNamespace()
CONTROL_CODE.HANDSHAKE = 0x41
CONTROL_CODE.DATA = 0x42
CONTROL_CODE.INFO = 0x43
CONTROL_CODE.REQUEST = 0x45
CONTROL_CODE.HEARTBEAT = 0x47
CONTROL_CODE.REPORT = 0x48

MODBUS_CODE = types.SimpleNamespace()
MODBUS_CODE.READ_COILS = 1
MODBUS_CODE.READ_DISCRETE_INPUTS = 2
MODBUS_CODE.READ_HOLDING_REGISTERS = 3
MODBUS_CODE.READ_INPUT = 4
MODBUS_CODE.WRITE_SINGLE_COIL = 5
MODBUS_CODE.WRITE_SINGLE_REGISTER = 6
MODBUS_CODE.WRITE_MULTIPLE_COILS = 15
MODBUS_CODE.WRITE_MULTIPLE_REGISTERS = 16

class FrameError(Exception):
    """Frame Validation Error"""

class NoSocketAvailableError(Exception):
    """No Socket Available Error"""

class NegativeAcknowledgeError(ModbusError):
    error_code = 7
    def __str__(self):
        return self.__doc__

error_code_to_exception_map |= {
    NegativeAcknowledgeError.error_code: NegativeAcknowledgeError
}

class Solarman:
    def __init__(self, serial, address, port, slave, timeout):
        self.serial = serial
        self.address = address
        self.port = port
        self.slave = slave
        self.timeout = timeout

        self.reader_task: asyncio.Task = None
        self.reader: asyncio.StreamReader = None
        self.writer: asyncio.StreamWriter = None
        self.data_queue = asyncio.Queue(maxsize = 1)
        self.data_wanted_ev = Event()

        self.sequence_number = None

        self.control_codes = CONTROL_CODE.__dict__.values()
        self.serial_bytes = struct.pack("<I", self.serial)

        self._handle_frame = self._handle_protocol_frame if serial > 0 else lambda: True
        self._get_response = self._get_rtu_response if serial > 0 else self._get_tcp_response
        self._adu = rtu if serial > 0 else tcp

    @staticmethod
    def _get_response_code(code: int) -> int:
        return code - 0x30

    @staticmethod
    def _calculate_checksum(data: bytes) -> int:
        checksum = 0
        for d in data:
            checksum += d & 0xFF
        return int(checksum & 0xFF)

    @staticmethod
    def _calculate_protocol_frame_checksum(frame: bytes) -> int:
        return Solarman._calculate_checksum(frame[1:-2])

    @property
    def connected(self):
        return self.reader_task and not self.reader_task.done()

    def _protocol_header(self, length: int, control: int, seq: bytes) -> bytearray:
        return bytearray(
            PROTOCOL.START
            + struct.pack("<H", length)
            + PROTOCOL.CONTROL_CODE_SUFFIX
            + struct.pack("<B", control)
            + seq
            + self.serial_bytes
        )

    def _protocol_trailer(self, data: bytes) -> bytearray:
        return bytearray(struct.pack("<B", self._calculate_checksum(data[1:])) + PROTOCOL.END)

    def _get_next_sequence_number(self) -> int:
        self.sequence_number = randrange(0x01, 0xFF) if self.sequence_number is None else (self.sequence_number + 1) & 0xFF
        return self.sequence_number

    def _frame_encoder(self, modbus_frame: bytes) -> bytearray:
        header = self._protocol_header(
            15 + len(modbus_frame),
            CONTROL_CODE.REQUEST,
            struct.pack("<H", self._get_next_sequence_number())
        )
        payload = bytearray(
            PROTOCOL.FRAME_TYPE
            + PROTOCOL.PLACEHOLDER1 # sensor type
            + PROTOCOL.PLACEHOLDER2 # delivery time
            + PROTOCOL.PLACEHOLDER2 # power on time
            + PROTOCOL.PLACEHOLDER2 # offset time
            + modbus_frame
        )
        frame = header + payload
        return frame + self._protocol_trailer(frame)

    def _frame_decoder(self, frame: bytes) -> bytearray:
        if (frame[0] != int.from_bytes(PROTOCOL.START, byteorder="big")) or (
            frame[-1] != int.from_bytes(PROTOCOL.END, byteorder="big")
        ):
            raise FrameError("Frame contains invalid start or end values")
        if frame[-2] != self._calculate_protocol_frame_checksum(frame):
            raise FrameError("Frame contains invalid checksum")
        if frame[5] != self.sequence_number:
            raise FrameError("Frame contains invalid sequence number")
        if frame[7:11] != self.serial_bytes:
            raise FrameError("Frame contains incorrect data logger serial number")
        if frame[4] != self._get_response_code(CONTROL_CODE.REQUEST):
            raise FrameError("Frame contains incorrect control code")
        if frame[11] != int("02", 16):
            raise FrameError("Frame contains invalid frametype")

        modbus_frame = frame[25:-2]

        if len(modbus_frame) < 5:
            if len(modbus_frame) > 0 and (err := error_code_to_exception_map.get(modbus_frame[0])):
                raise FrameError(f"Modbus: {err.__name__}")
            raise FrameError("Frame does not contain a valid Modbus RTU frame")

        return modbus_frame

    def _time_response_frame(self, frame: bytes) -> bytearray:
        response_frame = self._protocol_header(10, self._get_response_code(frame[4]), frame[5:7]) + bytearray(
            + struct.pack("<H", 0x0100) # Frame & sensor type?
            + struct.pack("<I", int(time.time()))
            + struct.pack("<I", 0) # Offset?
        )
        response_frame[5] = (response_frame[5] + 1) & 0xFF
        return response_frame + self._protocol_trailer(response_frame)

    def _received_frame_is_valid(self, frame: bytes) -> bool:
        def is_tcp_frame(frame):
            if frame[4] == CONTROL_CODE.REQUEST and (frame_len := len(frame)) and frame_len > 6 and (f := int.from_bytes(frame[5:6], byteorder = "big") == len(frame[6:])):
                return (f and int.from_bytes(frame[8:9], byteorder = "big") == len(frame[9:])) if frame_len > 9 else f # [0xa5, 0x17, 0x00, 0x10, 0x45, 0x03, 0x00, 0x98, 0x02]
            return False
        if not frame.startswith(PROTOCOL.START) or not frame.endswith(PROTOCOL.END):
            _LOGGER.debug("[%s] PROTOCOL_MISMATCH: %s", self.serial, frame.hex(" "))
            return False
        if frame[5] != self.sequence_number:
            if is_tcp_frame(frame):
                _LOGGER.debug("[%s] TCP_DETECTED: %s", self.serial, frame.hex(" "))
                self._handle_frame = lambda: True
                self._get_response = self._get_tcp_response
                self._adu = tcp
                return True
            _LOGGER.debug("[%s] SEQ_NO_MISMATCH: %s", self.serial, frame.hex(" "))
            return False
        return True

    def _received_frame_response(self, frame: bytes) -> tuple[bool, bytearray]:
        do_continue = True
        response_frame = None
        if frame[4] != CONTROL_CODE.REQUEST and frame[4] in self.control_codes:
            do_continue = False
            # Maybe do_continue = True for CONTROL_CODE.DATA|INFO|REPORT and thus process packets in the future?
            control_name = [i for i in CONTROL_CODE.__dict__ if CONTROL_CODE.__dict__[i]==frame[4]][0]
            _LOGGER.debug("[%s] PROTOCOL_%s: %s", self.serial, control_name, frame.hex(" "))
            response_frame = self._time_response_frame(frame)
            _LOGGER.debug("[%s] PROTOCOL_%s RESP: %s", self.serial, control_name, response_frame.hex(" "))
        return do_continue, response_frame

    def _send_receive_except(self, e: Exception) -> Exception | None:
        match e:
            case AttributeError():
                return NoSocketAvailableError("Connection already closed")
            case OSError() if e.errno == errno.EHOSTUNREACH:
                return TimeoutError
            case _:
                return None

    async def _handle_protocol_frame(self, frame):
        if (do_continue := self._received_frame_is_valid(frame)) == True:
            do_continue, response_frame = self._received_frame_response(frame)
            if response_frame is not None:
                try:
                    self.writer.write(response_frame)
                    await self.writer.drain()
                except Exception as e:
                    if (err := self._send_receive_except(e)) is not None:
                        e = err
                    _LOGGER.debug(f"[{self.serial}] PROTOCOL error: {type(e).__name__}{f': {e}' if f'{e}' else ''}")
        return do_continue

    async def _conn_keeper(self) -> None:
        while True:
            try:
                data = await self.reader.read(1024)
            except ConnectionResetError:
                _LOGGER.debug("[%s] Connection reset. Closing the socket reader.", self.serial, exc_info = True)
                break
            if data == b"":
                _LOGGER.debug("[%s] Connection closed by the remote. Closing the socket reader.", self.serial)
                break
            if not await self._handle_frame(data):
                continue
            if self.data_wanted_ev.is_set():
                if not self.data_queue.empty():
                    _ = self.data_queue.get_nowait()
                self.data_queue.put_nowait(data)
                self.data_wanted_ev.clear()
            else:
                _LOGGER.debug("Data received but nobody waits for it... Discarded")
        self.reader = None
        self.writer = None
        _LOGGER.debug("[%s] Auto reconnect enabled. Will try to restart the socket reader", self.serial)
        loop = asyncio.get_running_loop()
        loop.create_task(self.reconnect(), name="ReconnKeeper")

    async def _connect(self) -> None:
        try:
            if self.reader_task:
                self.reader_task.cancel()
            self.reader, self.writer = await asyncio.wait_for(asyncio.open_connection(self.address, self.port), self.timeout)
            loop = asyncio.get_running_loop()
            self.reader_task = loop.create_task(self._conn_keeper(), name="ConnKeeper")
        except:
            self.reader_task = None
            raise

    async def connect(self) -> None:
        try:
            await self._connect()
        except Exception as e:
            raise NoSocketAvailableError(
                f"Cannot open connection to {self.address}"
            ) from e

    async def reconnect(self) -> None:
        try:
            await self._connect()
            _LOGGER.debug("[%s] Successful reconnect", self.serial)
            if self.data_wanted_ev.is_set():
                _LOGGER.debug("[%s] Data expected. Will retry the last request", self.serial)
                self.writer.write(self._last_frame)
                await self.writer.drain()
        except Exception as e:
            _LOGGER.debug(f"Cannot open connection to {self.address}. [{type(e).__name__}{f': {e}' if f'{e}' else ''}]")
            await asyncio.sleep(0.5)
            await self.reconnect()

    async def disconnect(self) -> None:
        try:
            if (task := (t,) if (t := [task for task in asyncio.all_tasks() if task.get_name() == "ReconnKeeper"]) and len(t) > 0 else None):
                task.cancel()
            if self.reader_task:
                self.reader_task.cancel()
            if self.writer:
                try:
                    self.writer.write(b"")
                    await self.writer.drain()
                except (AttributeError, ConnectionResetError) as e:
                    _LOGGER.debug(f"{e} can be during closing ignored.")
                finally:
                    self.writer.close()
                    try:
                        await self.writer.wait_closed()
                    except OSError as e:  # Happens when host is unreachable.
                        _LOGGER.debug(f"{e} can be during closing ignored.")
        finally:
            self.reader_task = None
            self.reader = None
            self.writer = None

    async def _send_receive_frame(self, frame: bytes) -> bytes:
        if not self.connected:
            await self.connect()
        _LOGGER.debug("[%s] SENT: %s", self.serial, frame.hex(" "))
        self.data_wanted_ev.set()
        self._last_frame = frame
        try:
            self.writer.write(frame)
            await self.writer.drain()
            if (response_frame := await asyncio.wait_for(self.data_queue.get(), self.timeout)) == b"":
                raise NoSocketAvailableError("Connection closed on read. Retry if auto-reconnect is enabled")
        except Exception as e:
            if (err := self._send_receive_except(e)) is not None:
                raise err from e
            raise
        finally:
            self.data_wanted_ev.clear()
        _LOGGER.debug("[%s] RECD: %s", self.serial, response_frame.hex(" "))
        return response_frame

    async def _get_rtu_response(self, frame: bytes) -> bytearray:
        return self._frame_decoder(await self._send_receive_frame(self._frame_encoder(frame)))

    async def _get_tcp_response(self, frame: bytes) -> bytearray:
        def compatibility(response, request):
            return response if not 8 <= (l := len(response)) <= 10 else response[:5] + b'\x06' + response[6:] + (request[l:10] if len(request) > 12 else (b'\x00' * (10 - l))) + b'\x00\x01'
        return compatibility(await self._send_receive_frame(frame), frame)

    async def _get_modbus_response(self, request_frame: bytes):
        response_frame = await self._get_response(request_frame)
        try:
            return self._adu.parse_response_adu(response_frame, request_frame)
        except struct.error as e:
            if response_frame.endswith(PROTOCOL.PLACEHOLDER1) and (stripped := response_frame[:-2]) is not None and get_crc(stripped[:-2]) == stripped[-2:]:
                return self._adu.parse_response_adu(stripped, request_frame)
            raise e

    async def read_write(self, code, address, arg):
        match code:
            case MODBUS_CODE.READ_COILS:
                return await self._get_modbus_response(self._adu.read_coils(self.slave, address, arg))
            case MODBUS_CODE.READ_DISCRETE_INPUTS:
                return await self._get_modbus_response(self._adu.read_discrete_inputs(self.slave, address, arg))
            case MODBUS_CODE.READ_HOLDING_REGISTERS:
                return await self._get_modbus_response(self._adu.read_holding_registers(self.slave, address, arg))
            case MODBUS_CODE.READ_INPUT:
                return await self._get_modbus_response(self._adu.read_input_registers(self.slave, address, arg))
            case MODBUS_CODE.WRITE_SINGLE_COIL:
                return await self._get_modbus_response(self._adu.write_single_coil(self.slave, address, arg))
            case MODBUS_CODE.WRITE_SINGLE_REGISTER:
                return await self._get_modbus_response(self._adu.write_single_register(self.slave, address, arg if isinstance(arg, list) else [arg]))
            case MODBUS_CODE.WRITE_MULTIPLE_COILS:
                return await self._get_modbus_response(self._adu.write_multiple_coils(self.slave, address, arg))
            case MODBUS_CODE.WRITE_MULTIPLE_REGISTERS:
                return await self._get_modbus_response(self._adu.write_multiple_registers(self.slave, address, arg if isinstance(arg, list) else [arg]))
            case _:
                raise Exception("[%s] Used invalid modbus function code %d", self.serial, code)
