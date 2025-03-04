import time
import types
import errno
import struct
import logging
import asyncio

from multiprocessing import Event
from random import randrange, randint

from pymodbus.pdu.decoders import bit_msg, reg_msg, DecodePDU
from pymodbus.framer import FramerRTU, FramerSocket

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

FUNCTION_CODE = types.SimpleNamespace()
FUNCTION_CODE.READ_COILS = bit_msg.ReadCoilsRequest.function_code
FUNCTION_CODE.READ_DISCRETE_INPUTS = bit_msg.ReadDiscreteInputsRequest.function_code
FUNCTION_CODE.READ_HOLDING_REGISTERS = reg_msg.ReadHoldingRegistersRequest.function_code
FUNCTION_CODE.READ_INPUT_REGISTERS = reg_msg.ReadInputRegistersRequest.function_code
FUNCTION_CODE.WRITE_SINGLE_COIL = bit_msg.WriteSingleCoilRequest.function_code
FUNCTION_CODE.WRITE_SINGLE_REGISTER = reg_msg.WriteSingleRegisterRequest.function_code
FUNCTION_CODE.WRITE_MULTIPLE_COILS = bit_msg.WriteMultipleCoilsRequest.function_code
FUNCTION_CODE.WRITE_MULTIPLE_REGISTERS = reg_msg.WriteMultipleRegistersRequest.function_code

class FrameError(Exception):
    """Frame Validation Error"""

class NoSocketAvailableError(Exception):
    """No Socket Available Error"""

class Solarman:
    def __init__(self, serial, address, port, slave, timeout):
        self.serial = serial
        self.address = address
        self.port = port
        self.slave = slave
        self.timeout = timeout

        self.serial_bytes = struct.pack("<I", self.serial)

        self.open_task: asyncio.Task = None
        self.reader_task: asyncio.Task = None
        self.reader: asyncio.StreamReader = None
        self.writer: asyncio.StreamWriter = None
        self.data_queue = asyncio.Queue(maxsize = 1)
        self.data_wanted_ev = Event()

        self._server_decoder = DecodePDU(True)
        self._client_decoder = DecodePDU(False)
        self._server_framer = FramerRTU(self._server_decoder) if serial > 0 else FramerSocket(self._server_decoder)
        self._client_framer = FramerRTU(self._client_decoder) if serial > 0 else FramerSocket(self._client_decoder)
        self._get_response = self._parse_adu_from_rtu_response if serial > 0 else self._parse_adu_from_tcp_response
        self._handle_frame = self._handle_protocol_frame if serial > 0 else None

        self.sequence_number = None

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
    def connected(self):
        return self.reader_task and not self.reader_task.done()

    def _protocol_header(self, length: int, control: int, seq: bytes) -> bytearray:
        return bytearray(PROTOCOL.START
            + struct.pack("<H", length)
            + PROTOCOL.CONTROL_CODE_SUFFIX
            + struct.pack("<B", control)
            + seq
            + self.serial_bytes)

    def _protocol_trailer(self, data: bytes) -> bytearray:
        return bytearray(struct.pack("<B", self._calculate_checksum(data[1:])) + PROTOCOL.END)

    def _get_next_sequence_number(self) -> int:
        self.sequence_number = randrange(0x01, 0xFF) if self.sequence_number is None else (self.sequence_number + 1) & 0xFF
        return self.sequence_number

    def _received_frame_is_valid(self, frame: bytes) -> bool:
        if not frame.startswith(PROTOCOL.START):
            _LOGGER.debug("[%s] PROTOCOL_MISMATCH: %s", self.serial, frame.hex(" "))
            return False
        if frame[5] != self.sequence_number:
            if frame[4] == PROTOCOL.CONTROL_CODE.REQUEST and len(frame) > 6 and (f := int.from_bytes(frame[5:6], "big") == len(frame[6:])) and (int.from_bytes(frame[8:9], "big") == len(frame[9:]) if len(frame) > 9 else f):
                _LOGGER.debug("[%s] TCP_DETECTED: %s", self.serial, frame.hex(" "))
                self._server_framer = FramerSocket(self._server_decoder)
                self._client_framer = FramerSocket(self._client_decoder)
                self._get_response = self._parse_adu_from_tcp_response
                self._handle_frame = None
                return True
            _LOGGER.debug("[%s] SEQ_MISMATCH: %s", self.serial, frame.hex(" "))
            return False
        if not frame.endswith(PROTOCOL.END):
            _LOGGER.debug("[%s] PROTOCOL_MISMATCH: %s", self.serial, frame.hex(" "))
            return False
        if frame[7:11] != self.serial_bytes: # Serial number correction
            _LOGGER.debug("[%s] SERIAL_MISMATCH: %s", self.serial, frame.hex(" "))
            self.serial_bytes = frame[7:11]
            return True
        return True

    def _received_frame_response(self, frame: bytes) -> tuple[bool, bytearray]:
        do_continue = True
        response_frame = None
        if frame[4] != PROTOCOL.CONTROL_CODE.REQUEST and frame[4] in PROTOCOL.CONTROL_CODES:
            do_continue = False
            # Maybe do_continue = True for CONTROL_CODE.DATA|INFO|REPORT and thus process packets in the future?
            control_name = [i for i in PROTOCOL.CONTROL_CODE.__dict__ if PROTOCOL.CONTROL_CODE.__dict__[i] == frame[4]][0]
            _LOGGER.debug("[%s] PROTOCOL_%s: %s", self.serial, control_name, frame.hex(" "))
            response_frame = self._protocol_header(10, self._get_response_code(frame[4]), frame[5:7]) + bytearray(PROTOCOL.PLACEHOLDER1 # Frame Type
                + PROTOCOL.STATUS
                + struct.pack("<I", int(time.time()))
                + PROTOCOL.PLACEHOLDER3) # Offset?
            response_frame[5] = (response_frame[5] + 1) & 0xFF
            response_frame += self._protocol_trailer(response_frame)
            _LOGGER.debug("[%s] PROTOCOL_%s RESP: %s", self.serial, control_name, response_frame.hex(" "))
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
            _LOGGER.exception("[%s] Write error: %s", self.serial, e)

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
                _LOGGER.debug("[%s] Connection is reset by the peer. Will try to restart the connection", self.serial)
                break
            if data == b"":
                _LOGGER.debug("[%s] Connection closed by the remote. Will try to restart the connection", self.serial)
                break
            if self._handle_frame is not None and not await self._handle_frame(data):
                # Skip...
                continue
            if not self.data_wanted_ev.is_set():
                _LOGGER.debug("[%s] Data received but nobody waits for it... Discarded", self.serial)
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
                _LOGGER.debug("[%s] Successful reconnection! Data expected. Will retry the last request", self.serial)
                await self._write(self._last_frame)
            else:
                _LOGGER.debug("[%s] Successful connection!", self.serial)
            self.open_task = None
        except Exception as e:
            if self.data_wanted_ev.is_set():
                _LOGGER.debug(f"[{self.serial}] {e!r}")
                await self._open_connection()
            else:
                raise NoSocketAvailableError(f"Cannot open connection to {self.address}") from e

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
                _LOGGER.debug(f"[{self.serial}] {e} can be during closing ignored")
            finally:
                try:
                    self.writer.close()
                    await self.writer.wait_closed()
                except (AttributeError, OSError) as e: # OSError happens when is host unreachable
                    _LOGGER.debug(f"[{self.serial}] {e} can be during closing ignored")
                self.writer = None

    async def _send_receive_frame(self, frame: bytes) -> bytes:
        await self.open()
        _LOGGER.debug("[%s] SENT: %s", self.serial, frame.hex(" "))
        self.data_wanted_ev.set()
        self._last_frame = frame
        try:
            await self._write(frame)
            while True:
                try:
                    response_frame = await asyncio.wait_for(self.data_queue.get(), self.timeout)
                    _LOGGER.debug("[%s] RECD: %s", self.serial, response_frame.hex(" "))
                    return response_frame
                except TimeoutError:
                    _LOGGER.debug("[%s] Peer not responding. Closing connection", self.serial)
                    await self._close()
                    continue
        finally:
            self.data_wanted_ev.clear()

    async def _parse_adu_from_rtu_response(self, frame: bytes) -> bytes:
        request_frame = self._protocol_header(15 + len(frame),
            PROTOCOL.CONTROL_CODE.REQUEST,
            struct.pack("<H", self._get_next_sequence_number())
        ) + bytearray(PROTOCOL.FRAME_TYPE
            + PROTOCOL.PLACEHOLDER2 # sensor type
            + PROTOCOL.PLACEHOLDER4 # delivery|poweron|offset time
            + frame)
        response_frame = await self._send_receive_frame(request_frame + self._protocol_trailer(request_frame))
        if response_frame[4] != self._get_response_code(PROTOCOL.CONTROL_CODE.REQUEST):
            raise FrameError("Incorrect control code")
        if response_frame[5] != self.sequence_number:
            raise FrameError("Invalid sequence number")
        if response_frame[11:12] != PROTOCOL.FRAME_TYPE:
            raise FrameError("Invalid frame type")
        if response_frame[-2] != self._calculate_checksum(response_frame[1:-2]):
            raise FrameError("Invalid checksum")
        adu = response_frame[25:-2]
        if len(adu) < 5: # Short version of modbus exception response
            raise FrameError(f"Modbus exception response: 0x{adu[0]:02X}")
        if adu.endswith(PROTOCOL.PLACEHOLDER2) and FramerRTU.compute_CRC(adu[:-4]).to_bytes(2, "big") == adu[-4:-2]: # Double CRC (XXXX0000) correction
            return adu[:-2]
        return adu

    async def _parse_adu_from_tcp_response(self, frame: bytes) -> bytes:
        adu = await self._send_receive_frame(frame)
        if 8 <= len(adu) <= 10: # Incomplete response frame correction
            return adu[:5] + b'\x06' + adu[6:] + (frame[len(adu):10] if len(frame) > 12 else (b'\x00' * (10 - len(adu)))) + b'\x00\x01'
        return adu

    async def execute(self, code, **kwargs):
        if code in self._server_decoder.lookup:
            if "registers" in kwargs and not isinstance(kwargs["registers"], list):
                kwargs["registers"] = [kwargs["registers"]]
            elif "bits" in kwargs and not isinstance(kwargs["bits"], list):
                kwargs["bits"] = [kwargs["bits"]]
            _, pdu = self._client_framer.processIncomingFrame(await self._get_response(self._server_framer.buildFrame(self._server_decoder.lookup.get(code)(dev_id = self.slave, transaction_id = randint(0, 65535), **kwargs))))
            if pdu is None:
                raise FrameError(f"Invalid modbus response received")
            if pdu.function_code != code:
                raise FrameError(f"Incorrect response w/ function code {pdu.function_code} instead of {code} received")
            if FUNCTION_CODE.READ_HOLDING_REGISTERS <= code <= FUNCTION_CODE.READ_INPUT_REGISTERS:
                return pdu.registers
            if FUNCTION_CODE.READ_COILS <= code <= FUNCTION_CODE.READ_DISCRETE_INPUTS:
                return pdu.bits
            return pdu.count
        raise Exception("[%s] Used invalid modbus function code %d", self.serial, code)

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
