import time
import errno
import struct
import socket
import logging
import asyncio
import threading
import concurrent.futures

from datetime import datetime

from pysolarmanv5 import PySolarmanV5Async, V5FrameError
from umodbus.client.tcp import read_coils, read_discrete_inputs, read_holding_registers, read_input_registers, write_single_coil, write_multiple_coils, write_single_register, write_multiple_registers, parse_response_adu

from homeassistant.helpers.update_coordinator import UpdateFailed

from .const import *
from .common import *
from .parser import ParameterParser

_LOGGER = logging.getLogger(__name__)

class PySolarmanV5AsyncWrapper(PySolarmanV5Async):
    _passthrough = False

    def __init__(self, address, serial, port, mb_slave_id):
        super().__init__(address, serial, port = port, mb_slave_id = mb_slave_id, logger = _LOGGER, auto_reconnect = AUTO_RECONNECT, socket_timeout = TIMINGS_SOCKET_TIMEOUT)

    async def _tcp_parse_response_adu(self, mb_request_frame):
        return parse_response_adu(await self._send_receive_v5_frame(mb_request_frame), mb_request_frame)

    def _received_frame_is_valid(self, frame):
        if self._passthrough:
            return True
        if not frame.startswith(self.v5_start):
            self.log.debug("[%s] V5_MISMATCH: %s", self.serial, frame.hex(" "))
            return False
        if frame[5] != self.sequence_number and is_ethernet_frame(frame):
            self.log.debug("[%s] V5_ETHERNET_DETECTED: %s", self.serial, frame.hex(" "))
            self._passthrough = True
            return False
        if frame[5] != self.sequence_number:
            self.log.debug("[%s] V5_SEQ_NO_MISMATCH: %s", self.serial, frame.hex(" "))
            return False
        if frame.startswith(self.v5_start + b"\x01\x00\x10\x47"):
            self.log.debug("[%s] COUNTER: %s", self.serial, frame.hex(" "))
            return False
        return True

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

class Inverter(PySolarmanV5AsyncWrapper):
    _is_busy = 0

    auto_reconnect = AUTO_RECONNECT
    state = -1
    state_interval = 0
    state_updated = datetime.now()
    device_info = {}
    profile = None

    async def load(self, name, mac, path, file):
        self.name = name

        if (n := process_profile(file if file else "deye_hybrid.yaml")) and (p := await yaml_open(path + n)):
            self.device_info = build_device_info(self.serial, mac, name, p["info"] if "info" in p else None, n)
            self.profile = ParameterParser(p)

        _LOGGER.debug(self.device_info)

    def get_sensors(self):
        return self.profile.get_sensors() if self.profile else []

    def available(self):
        return self.state > -1

    def get_connection_state(self):
        if self.state > 0:
            return "Connected"
        return "Disconnected"

    async def shutdown(self) -> None:
        self.state = -1
        await self.disconnect()

    async def read_write(self, code, start, arg):
        await self.connect()

        match code:
            case CODE.READ_COILS:
                return await self.read_coils(start, arg)
            case CODE.READ_DISCRETE_INPUTS:
                return await self.read_discrete_inputs(start, arg)
            case CODE.READ_HOLDING_REGISTERS:
                return await self.read_holding_registers(start, arg)
            case CODE.READ_INPUT:
                return await self.read_input_registers(start, arg)
            case CODE.WRITE_SINGLE_COIL:
                return await self.write_single_coil(start, arg)
            case CODE.WRITE_HOLDING_REGISTER:
                return await self.write_holding_register(start, arg)
            case CODE.WRITE_MULTIPLE_COILS:
                return await self.write_multiple_coils(start, arg)
            case CODE.WRITE_MULTIPLE_HOLDING_REGISTERS:
                return await self.write_multiple_holding_registers(start, arg)
            case _:
                raise Exception(f"[{self.serial}] Used incorrect modbus function code {code}")

    async def wait_for_done(self, attempts_left = ACTION_ATTEMPTS):
        while self._is_busy == 1 and attempts_left > 0:
            attempts_left -= 1
            await asyncio.sleep(TIMINGS_WAIT_FOR_SLEEP)
        return self._is_busy == 1

    def get_result(self, middleware = None):
        result = middleware.get_result() if middleware else {}
        result_count = len(result) if result else 0

        if result_count > 0:
            _LOGGER.debug(f"[{self.serial}] Returning {result_count} new values to the Coordinator. [Previous State: {self.get_connection_state()} ({self.state})]")
            now = datetime.now()
            self.state_interval = now - self.state_updated
            self.state_updated = now
            self.state = 1

        return result

    async def get_failed(self):
        _LOGGER.debug(f"[{self.serial}] Request failed. [Previous State: {self.get_connection_state()} ({self.state})]")

        self.state = 0 if self.state == 1 else -1

        await self.disconnect()

        return self.state == -1

    async def get(self, runtime = 0):
        requests = self.profile.get_requests(runtime)
        requests_count = len(requests) if requests else 0
        responses = {}

        _LOGGER.debug(f"[{self.serial}] Scheduling {requests_count} query request{'' if requests_count == 1 else 's'}. #{runtime}")

        if await self.wait_for_done(ACTION_ATTEMPTS):
            _LOGGER.debug(f"[{self.serial}] get: Timeout.")
            raise TimeoutError(f"[{self.serial}] Currently writing data to the device!")

        self._is_busy = 1

        try:
            async with asyncio.timeout(TIMINGS_UPDATE_TIMEOUT):
                for request in requests:
                    code = get_request_code(request)
                    start = get_request_start(request)
                    end = get_request_end(request)
                    quantity = end - start + 1

                    start_end = f"{start:04} - {end:04} | 0x{start:04X} - 0x{end:04X} # {quantity:03}"
                    _LOGGER.debug(f"[{self.serial}] Querying {start_end} ...")

                    attempts_left = ACTION_ATTEMPTS
                    while attempts_left > 0 and not start in responses:
                        attempts_left -= 1

                        try:
                            responses[start] = [quantity, await self.read_write(code, start, quantity)]
                            _LOGGER.debug(f"[{self.serial}] Querying {start_end} succeeded.")
                        except (V5FrameError, TimeoutError, Exception) as e:
                            _LOGGER.debug(f"[{self.serial}] Querying {start_end} failed, attempts left: {attempts_left}{'' if attempts_left > 0 else ', aborting.'} [{format_exception(e)}]")

                            if not self.auto_reconnect:
                                await self.disconnect()

                            if not attempts_left > 0:
                                raise

                            await asyncio.sleep((ACTION_ATTEMPTS - attempts_left) * TIMINGS_WAIT_SLEEP)

                self.profile.process(responses)

        except TimeoutError:
            if await self.get_failed():
                raise
            _LOGGER.debug(f"[{self.serial}] Timeout fetching {self.name} data")
        except Exception as e:
            if await self.get_failed():
                raise UpdateFailed(f"[{self.serial}] {format_exception(e)}") from e
            _LOGGER.debug(f"[{self.serial}] Error fetching {self.name} data: {e}")
        finally:
            self._is_busy = 0

        return self.get_result(self.profile)

    async def call(self, code, start, arg, wait_for_attempts = ACTION_ATTEMPTS):
        _LOGGER.debug(f"[{self.serial}] call code {code}: {start} | 0x{start:04X}, arg: {arg}, wait_for_attempts: {wait_for_attempts}")

        if await self.wait_for_done(wait_for_attempts):
            _LOGGER.debug(f"[{self.serial}] call code {code}: Timeout.")
            raise TimeoutError(f"[{self.serial}] Coordinator is currently reading data from the device!")

        self._is_busy = 1

        try:
            attempts_left = ACTION_ATTEMPTS
            while attempts_left > 0:
                attempts_left -= 1

                try:
                    response = await self.read_write(code, start, arg)
                    _LOGGER.debug(f"[{self.serial}] call code {code}: {start} | 0x{start:04X}, response: {response}")
                    return response
                except Exception as e:
                    _LOGGER.debug(f"[{self.serial}] call code {code}: {start} | 0x{start:04X}, arg: {arg} failed, attempts left: {attempts_left}. [{format_exception(e)}]")

                    if not self.auto_reconnect:
                        await self.disconnect()

                    if not attempts_left > 0:
                        raise

                    await asyncio.sleep(TIMINGS_WAIT_SLEEP)
        except:
            raise
        finally:
            self._is_busy = 0
