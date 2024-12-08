import time
import errno
import socket
import logging
import asyncio
import threading
import concurrent.futures

from datetime import datetime

from umodbus.client.tcp import read_coils, read_discrete_inputs, read_holding_registers, read_input_registers, write_single_coil, write_multiple_coils, write_single_register, write_multiple_registers, parse_response_adu

from homeassistant.helpers.update_coordinator import UpdateFailed

from .const import *
from .common import *
from .provider import *
from .include.pysolarmanv5 import PySolarmanV5Async, V5FrameError

_LOGGER = logging.getLogger(__name__)

class PySolarmanV5AsyncWrapper(PySolarmanV5Async):
    def __init__(self, address, serial, port, mb_slave_id):
        super().__init__(address, serial, port = port, mb_slave_id = mb_slave_id, logger = _LOGGER, auto_reconnect = AUTO_RECONNECT, socket_timeout = TIMINGS_SOCKET_TIMEOUT)

    @property
    def connected(self):
        return self.reader_task

    @property
    def auto_reconnect(self):
        return self._needs_reconnect

    async def connect(self) -> None:
        if not self.reader_task:
            _LOGGER.info(f"[{self.serial}] Connecting to {self.address}:{self.port}")
            await super().connect()
        # ! Gonna have to rewrite the state handling in the future as it's now after all the development and tunning mess AF !
        #elif not self.state > 0:
        #    await super().reconnect()

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
        return mb_response_adu if not len(mb_response_adu := await self._send_receive_v5_frame(mb_request_frame)) == 10 else mb_response_adu + b'\x00\x01'

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

class Inverter():
    def __init__(self, config: ConfigurationProvider):
        self._is_busy = 0
        self._write_lock = True

        self.state = -1
        self.state_interval = 0
        self.state_updated = datetime.now()
        self.config: ConfigurationProvider = config
        self.endpoint: EndPointProvider = None
        self.profile: ProfileProvider = None
        self.modbus: PySolarmanV5AsyncEthernetWrapper = None
        self.device_info = {}

    @property
    def available(self):
        return self.state > -1

    @property
    def get_connection_state(self):
        return "Connected" if self.state > 0 else "Disconnected"

    async def load(self):
        try:
            self.endpoint = await EndPointProvider(self.config).discover()
            self.profile = ProfileProvider(self.config, self.endpoint)
            self.modbus = PySolarmanV5AsyncEthernetWrapper(*self.endpoint.connection)
            self.device_info = await self.profile.resolve(self.get)
            _LOGGER.debug(self.device_info)
        except BaseException as e:
            raise UpdateFailed(f"[{self.config.serial}] Device loading failed. [{format_exception(e)}]") from e

    def get_entity_descriptions(self):
        return (STATE_SENSORS + self.profile.parser.get_entity_descriptions()) if self.profile and self.profile.parser else []

    async def shutdown(self) -> None:
        self.state = -1
        await self.modbus.disconnect()

    async def read_write(self, code, start, arg):
        if not self.modbus.connected:
            self.state_updated = datetime.now()
        await self.modbus.connect()

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

    async def safe_read_write(self, code, start, arg):
        if (response := await self.read_write(code, start, arg)) and (length := ilen(response)) and (expected := arg if code < CODE.WRITE_SINGLE_COIL else 1) and length != expected:
            raise Exception(f"[{self.config.serial}] Unexpected response: Invalid length! (Length: {length}, Expected: {expected})")
        return response

    async def raise_when_busy(self, attempts_left = ACTION_ATTEMPTS, message = "Semaphore timeout."):
        async def wait_for_done(attempts_left):
            try:
                try:
                    while self._is_busy == 1 and attempts_left > 0:
                        attempts_left -= 1
                        await asyncio.sleep(TIMINGS_WAIT_FOR_SLEEP)
                except Exception as e:
                    _LOGGER.debug(f"wait_for_done: {format_exception(e)}")
                return self._is_busy == 1
            finally:
                self._is_busy = 1

        if await wait_for_done(attempts_left):
            _LOGGER.debug(f"[{self.config.serial}] R/W Timeout.")
            raise UpdateFailed(f"[{self.config.serial}] {message}")

    async def get_failed(self):
        _LOGGER.debug(f"[{self.config.serial}] Fetching failed. [Previous State: {self.get_connection_state} ({self.state})]")
        self.state = 0 if self.state == 1 else -1

        await self.modbus.disconnect()

        return self.state == -1

    async def get(self, runtime = 0, requests = None):
        scheduled = self.profile.parser.schedule_requests(runtime) if not requests else requests
        scheduled_count = len(scheduled) if scheduled else 0
        responses, result = {}, {}

        _LOGGER.debug(f"[{self.config.serial}] Scheduling {scheduled_count} query request{'' if scheduled_count == 1 else 's'}. #{runtime}")

        try:
            await self.raise_when_busy(message = "Busy: Currently writing to the device!")

            try:
                async with asyncio.timeout(TIMINGS_UPDATE_TIMEOUT):
                    for request in scheduled:
                        code, start, end = get_request_code(request), get_request_start(request), get_request_end(request)
                        quantity, code_start = end - start + 1, (code, start)
                        code_start_end = f"{code:02X} ~ {start:04} - {end:04} | 0x{start:04X} - 0x{end:04X} # {quantity:03}"
                        _LOGGER.debug(f"[{self.config.serial}] Querying {code_start_end} ...")

                        attempts_left = ACTION_ATTEMPTS
                        while attempts_left > 0 and not code_start in responses:
                            attempts_left -= 1

                            try:
                                responses[code_start] = await self.safe_read_write(code, start, quantity)
                                _LOGGER.debug(f"[{self.config.serial}] Querying {code_start_end} succeeded.")
                            except (V5FrameError, TimeoutError, Exception) as e:
                                _LOGGER.debug(f"[{self.config.serial}] Querying {code_start_end} failed, attempts left: {attempts_left}{'' if attempts_left > 0 else ', aborting.'} [{format_exception(e)}]")

                                if not self.modbus.auto_reconnect:
                                    await self.modbus.disconnect()

                                if not attempts_left > 0:
                                    raise

                                await asyncio.sleep((ACTION_ATTEMPTS - attempts_left) * TIMINGS_WAIT_SLEEP)

                    result = self.profile.parser.process(responses) if not requests else responses

                    if (rc := len(result) if result else 0) > 0 and (now := datetime.now()):
                        _LOGGER.debug(f"[{self.config.serial}] Returning {rc} new values to the Coordinator. [Previous State: {self.get_connection_state} ({self.state})]")
                        self.state_interval = now - self.state_updated
                        self.state_updated = now
                        self.state = 1

            except TimeoutError:
                raise
            except Exception as e:
                if await self.get_failed():
                    raise UpdateFailed(f"[{self.config.serial}] {format_exception(e)}") from e
                _LOGGER.debug(f"[{self.config.serial}] Error fetching {self.config.name} data: {e}")
            finally:
                self._is_busy = 0

        except TimeoutError:
            if await self.get_failed():
                raise
            _LOGGER.debug(f"[{self.config.serial}] Timeout fetching {self.config.name} data")

        return result

    def check(self, lock):
        if lock and self._write_lock:
            raise UserWarning("Entity is locked!")

    async def call(self, code, start, arg, wait_for_attempts = ACTION_ATTEMPTS):
        code_start_arg = f"{code:02X} ~ {start} | 0x{start:04X}: {arg}"
        _LOGGER.debug(f"[{self.config.serial}] Call {code_start_arg} ...")

        await self.raise_when_busy(wait_for_attempts, "Busy: The coordinator is currently reading data from the device!")

        try:
            attempts_left = ACTION_ATTEMPTS
            while attempts_left > 0:
                attempts_left -= 1

                try:
                    response = await self.safe_read_write(code, start, arg)
                    _LOGGER.debug(f"[{self.config.serial}] Call {code_start_arg} succeeded, response: {response}")
                    return response
                except Exception as e:
                    _LOGGER.debug(f"[{self.config.serial}] Call {code_start_arg} failed, attempts left: {attempts_left}{'' if attempts_left > 0 else ', aborting.'} [{format_exception(e)}]")

                    if not self.modbus.auto_reconnect:
                        await self.modbus.disconnect()

                    if not attempts_left > 0:
                        raise

                    await asyncio.sleep(TIMINGS_WAIT_SLEEP)
        except:
            raise
        finally:
            self._is_busy = 0
