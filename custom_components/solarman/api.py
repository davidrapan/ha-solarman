import time
import errno
import socket
import logging
import asyncio
import threading
import concurrent.futures

from datetime import datetime

from umodbus.client.tcp import read_coils, read_discrete_inputs, read_holding_registers, read_input_registers, write_single_coil, write_multiple_coils, write_single_register, write_multiple_registers, parse_response_adu

from .const import *
from .common import *
from .provider import *
from .include.pysolarmanv5 import PySolarmanV5Async

_LOGGER = logging.getLogger(__name__)

class PySolarmanV5AsyncWrapper(PySolarmanV5Async):
    def __init__(self, address, serial, port, mb_slave_id):
        super().__init__(address, serial, port = port, mb_slave_id = mb_slave_id, logger = _LOGGER, auto_reconnect = AUTO_RECONNECT, socket_timeout = TIMINGS_SOCKET_TIMEOUT)

    @property
    def auto_reconnect(self):
        return self._needs_reconnect

    async def connect(self) -> bool:
        if not self.reader_task:
            _LOGGER.info(f"[{self.serial}] Connecting to {self.address}:{self.port}")
            await super().connect()
            return True
        return False

    async def disconnect(self) -> None:
        _LOGGER.info(f"[{self.serial}] Disconnecting from {self.address}:{self.port}")
        try:
            await super().disconnect()
        finally:
            self.reader_task = None
            self.reader = None
            self.writer = None

class PySolarmanV5AsyncEthernetWrapper(PySolarmanV5AsyncWrapper):
    def __init__(self, address, serial, port, mb_slave_id):
        super().__init__(address, serial, port, mb_slave_id)
        self._passthrough = False

    async def _tcp_send_receive_frame(self, mb_request_frame):
        return mb_compatibility(await self._send_receive_v5_frame(mb_request_frame), mb_request_frame)

    async def _tcp_parse_response_adu(self, mb_request_frame):
        return parse_response_adu(await self._tcp_send_receive_frame(mb_request_frame), mb_request_frame)

    def _received_frame_is_valid(self, frame):
        if self._passthrough:
            return True
        if not frame.startswith(self.v5_start):
            self.log.debug("[%s] V5_MISMATCH: %s", self.serial, frame.hex(" "))
            return False
        if frame[5] != self.sequence_number and is_ethernet_frame(frame):
            self.log.debug("[%s] V5_ETHERNET_DETECTED: %s", self.serial, frame.hex(" "))
            self._passthrough = True
            return True
        if frame[5] != self.sequence_number:
            self.log.debug("[%s] V5_SEQ_NO_MISMATCH: %s", self.serial, frame.hex(" "))
            return False
        if frame.startswith(self.v5_start + b"\x01\x00\x10\x47"):
            self.log.debug("[%s] COUNTER: %s", self.serial, frame.hex(" "))
            return False
        return True

    async def read_coils(self, register_addr, quantity):
        if not self._passthrough:
            return await super().read_coils(register_addr, quantity)
        return await self._tcp_parse_response_adu(read_coils(self.mb_slave_id, register_addr, quantity))

    async def read_discrete_inputs(self, register_addr, quantity):
        if not self._passthrough:
            return await super().read_discrete_inputs(register_addr, quantity)
        return await self._tcp_parse_response_adu(read_discrete_inputs(self.mb_slave_id, register_addr, quantity))

    async def read_input_registers(self, register_addr, quantity):
        if not self._passthrough:
            return await super().read_input_registers(register_addr, quantity)
        return await self._tcp_parse_response_adu(read_input_registers(self.mb_slave_id, register_addr, quantity))

    async def read_holding_registers(self, register_addr, quantity):
        if not self._passthrough:
            return await super().read_holding_registers(register_addr, quantity)
        return await self._tcp_parse_response_adu(read_holding_registers(self.mb_slave_id, register_addr, quantity))

    async def write_single_coil(self, register_addr, value):
        if not self._passthrough:
            return await super().write_single_coil(register_addr, value)
        return await self._tcp_parse_response_adu(write_single_coil(self.mb_slave_id, register_addr, value))

    async def write_multiple_coils(self, register_addr, values):
        if not self._passthrough:
            return await super().write_multiple_coils(register_addr, values)
        return await self._tcp_parse_response_adu(write_multiple_coils(self.mb_slave_id, register_addr, values))

    async def write_holding_register(self, register_addr, value):
        if not self._passthrough:
            return await super().write_holding_register(register_addr, value)
        return await self._tcp_parse_response_adu(write_single_register(self.mb_slave_id, register_addr, value))

    async def write_multiple_holding_registers(self, register_addr, values):
        if not self._passthrough:
            return await super().write_multiple_holding_registers(register_addr, values)
        return await self._tcp_parse_response_adu(write_multiple_registers(self.mb_slave_id, register_addr, values))

class InverterState():
    def __init__(self):
        self.updated = datetime.now()
        self.updated_interval = 0
        self.value = -1

    @property
    def print(self):
        return "Connected" if self.value > 0 else "Disconnected"

    def update(self, reinit: bool = False):
        now = datetime.now()
        if reinit:
            self.updated = now
        else:
            self.updated_interval = now - self.updated
            self.updated = now
            self.value = 1

    def reevaluate(self) -> int:
        self.value = 0 if self.value == 1 else -1
        return self.value == -1

class Inverter():
    def __init__(self, config: ConfigurationProvider):
        self._semaphore = asyncio.Semaphore(1)
        self._write_lock = True

        self.state: InverterState = InverterState()
        self.config: ConfigurationProvider = config
        self.endpoint: EndPointProvider = None
        self.profile: ProfileProvider = None
        self.modbus: PySolarmanV5AsyncEthernetWrapper = None
        self.device_info: dict = {}

    @property
    def available(self):
        return self.state.value > -1

    async def load(self):
        try:
            self.endpoint = await EndPointProvider(self.config).discover()
            self.profile = ProfileProvider(self.config, self.endpoint)
            self.modbus = PySolarmanV5AsyncEthernetWrapper(*self.endpoint.connection)
            self.device_info = await self.profile.resolve(self.get)
            _LOGGER.debug(self.device_info)
        except BaseException as e:
            raise Exception(f"[{self.config.serial}] Device setup failed. [{format_exception(e)}]") from e

    def get_entity_descriptions(self):
        return (STATE_SENSORS + self.profile.parser.get_entity_descriptions()) if self.profile and self.profile.parser else []

    def check(self, lock):
        if lock and self._write_lock:
            raise UserWarning("Entity is locked!")

    async def shutdown(self) -> None:
        self.state.value = -1
        await self.modbus.disconnect()

    async def read_write(self, code, start, arg):
        if await self.modbus.connect():
            self.state.update(True)

        match code:
            case CODE.READ_COILS:
                return await self.modbus.read_coils(start, arg)
            case CODE.READ_DISCRETE_INPUTS:
                return await self.modbus.read_discrete_inputs(start, arg)
            case CODE.READ_HOLDING_REGISTERS:
                return await self.modbus.read_holding_registers(start, arg)
            case CODE.READ_INPUT:
                return await self.modbus.read_input_registers(start, arg)
            case CODE.WRITE_SINGLE_COIL:
                return await self.modbus.write_single_coil(start, arg)
            case CODE.WRITE_HOLDING_REGISTER:
                return await self.modbus.write_holding_register(start, arg)
            case CODE.WRITE_MULTIPLE_COILS:
                return await self.modbus.write_multiple_coils(start, ensure_list(arg))
            case CODE.WRITE_MULTIPLE_HOLDING_REGISTERS:
                return await self.modbus.write_multiple_holding_registers(start, ensure_list(arg))
            case _:
                raise Exception(f"[{self.serial}] Used incorrect modbus function code {code}")

    async def try_read_write(self, code, start, arg, message, incremental_wait):
        _LOGGER.debug(f"[{self.config.serial}] {message} ...")

        response = None

        attempts_left = ACTION_ATTEMPTS
        while attempts_left > 0 and response is None:
            attempts_left -= 1
            try:
                if (response := await self.read_write(code, start, arg)) and (length := ilen(response)) and (expected := arg if code < CODE.WRITE_SINGLE_COIL else 1) and length != expected:
                    raise Exception(f"[{self.config.serial}] Unexpected response: Invalid length! (Length: {length}, Expected: {expected})")

                _LOGGER.debug(f"[{self.config.serial}] {message} succeeded, response: {response}")
            except Exception as e:
                _LOGGER.debug(f"[{self.config.serial}] {message} failed, attempts left: {attempts_left}{'' if attempts_left > 0 else ', aborting.'} [{format_exception(e)}]")

                if not self.modbus.auto_reconnect:
                    await self.modbus.disconnect()
                if not attempts_left > 0:
                    raise
                await asyncio.sleep(((ACTION_ATTEMPTS - attempts_left) * TIMINGS_WAIT_SLEEP) if incremental_wait else TIMINGS_WAIT_SLEEP)
        
        return response

    async def get(self, runtime = 0, requests = None):
        scheduled, scheduled_count = ensure_list_safe_len(self.profile.parser.schedule_requests(runtime) if not requests else requests)
        responses, result = {}, {}

        _LOGGER.debug(f"[{self.config.serial}] Scheduling {scheduled_count} query request{'' if scheduled_count == 1 else 's'}. ^{runtime}")

        try:
            async with asyncio.timeout(TIMINGS_UPDATE_TIMEOUT):
                async with self._semaphore:
                    for request in scheduled:
                        code, start, end = get_request_code(request), get_request_start(request), get_request_end(request)
                        quantity = end - start + 1
                        responses[(code, start)] = await self.try_read_write(code, start, quantity, f"Querying {code:02X} ~ {start:04} - {end:04} | 0x{start:04X} - 0x{end:04X} #{quantity:03}", True)

                    result = self.profile.parser.process(responses) if not requests else responses

                    if (rc := len(result) if result else 0) > 0:
                        _LOGGER.debug(f"[{self.config.serial}] Returning {rc} new values to the Coordinator. [Previous State: {self.state.print} ({self.state.value})]")
                        self.state.update()

        except (TimeoutError, Exception) as e:
            _LOGGER.debug(f"[{self.config.serial}] Fetching failed. [Previous State: {self.state.print} ({self.state.value})]")
            if self.state.reevaluate():
                await self.modbus.disconnect()
                raise
            _LOGGER.debug(f"[{self.config.serial}] {"Timeout" if isinstance(e, TimeoutError) else "Error"} fetching {self.config.name} data: {format_exception(e)}")

        return result

    async def call(self, code, start, arg):
        _LOGGER.debug(f"[{self.config.serial}] Scheduling call request.")

        async with asyncio.timeout(TIMINGS_UPDATE_TIMEOUT):
            async with self._semaphore:
                return await self.try_read_write(code, start, arg, f"Call {code:02X} ~ {start} | 0x{start:04X}: {arg}", False)
