import logging
import asyncio
import threading
import concurrent.futures

from datetime import datetime

from .const import *
from .common import *
from .provider import *
from .include.pysolarmanv5 import PySolarmanAsync

_LOGGER = logging.getLogger(__name__)

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
        self.modbus: PySolarmanAsync = None
        self.device_info: dict = {}

    async def load(self):
        try:
            self.endpoint = await EndPointProvider(self.config).discover()
            self.profile = ProfileProvider(self.config, self.endpoint)
            self.modbus = PySolarmanAsync(*self.endpoint.connection, _LOGGER, AUTO_RECONNECT, TIMINGS_SOCKET_TIMEOUT)
            self.device_info = await self.profile.resolve(self.get)
            _LOGGER.debug(self.device_info)
        except TimeoutError as e:
            raise TimeoutError(f"[{self.config.serial}] Device setup timed out") from e
        except BaseException as e:
            raise Exception(f"[{self.config.serial}] Device setup failed. [{format_exception(e)}]") from e

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
            case CODE.WRITE_SINGLE_REGISTER:
                return await self.modbus.write_single_register(start, arg)
            case CODE.WRITE_MULTIPLE_COILS:
                return await self.modbus.write_multiple_coils(start, ensure_list(arg))
            case CODE.WRITE_MULTIPLE_REGISTERS:
                return await self.modbus.write_multiple_registers(start, ensure_list(arg))
            case _:
                raise Exception(f"[{self.serial}] Used incorrect modbus function code {code}")

    async def try_read_write(self, code, start, arg, message: str):
        _LOGGER.debug(f"[{self.config.serial}] {message} ...")

        response = None

        attempts_left = ACTION_ATTEMPTS
        while attempts_left > 0 and response is None:
            attempts_left -= 1
            try:
                if (response := await self.read_write(code, start, arg)) and (length := ilen(response)) is None and (expected := arg if code < CODE.WRITE_SINGLE_COIL else 1) and length != expected:
                    raise Exception(f"[{self.config.serial}] Unexpected response: Invalid length! (Length: {length}, Expected: {expected})")

                _LOGGER.debug(f"[{self.config.serial}] {message} succeeded, response: {response}")
            except Exception as e:
                _LOGGER.debug(f"[{self.config.serial}] {message} failed, attempts left: {attempts_left}{'' if attempts_left > 0 else ', aborting.'} [{format_exception(e)}]")

                if attempts_left == ACTION_ATTEMPTS - 2:
                    await self.endpoint.discover(True)
                if not self.modbus.auto_reconnect:
                    await self.modbus.disconnect()
                if not attempts_left > 0:
                    raise

                await asyncio.sleep(TIMINGS_WAIT_SLEEP)

        return response

    async def get(self, runtime = 0, requests = None):
        scheduled, scount = ensure_list_safe_len(self.profile.parser.schedule_requests(runtime) if requests is None else requests)
        responses, result = {}, {}

        _LOGGER.debug(f"[{self.config.serial}] Scheduling {scount} query request{'s' if scount != 1 else ''}. ^{runtime}")

        if scount == 0:
            return result

        try:
            async with asyncio.timeout(TIMINGS_UPDATE_TIMEOUT):
                async with self._semaphore:
                    for request in scheduled:
                        code, start, end = get_request_code(request), get_request_start(request), get_request_end(request)
                        quantity = end - start + 1
                        responses[(code, start)] = await self.try_read_write(code, start, quantity, f"Querying {code:02} ❘ 0x{code:02X} ~ {start:04} - {end:04} ❘ 0x{start:04X} - 0x{end:04X} #{quantity:03}")

                    result = self.profile.parser.process(responses) if requests is None else responses

                    if (rcount := len(result) if result else 0) > 0:
                        _LOGGER.debug(f"[{self.config.serial}] Returning {rcount} new value{'s' if rcount > 1 else ''}. [Previous State: {self.state.print} ({self.state.value})]")
                        self.state.update()

        except Exception as e:
            if self.state.reevaluate():
                await self.modbus.disconnect()
                raise
            _LOGGER.debug(f"[{self.config.serial}] {"Timeout" if isinstance(e, TimeoutError) else "Error"} fetching {self.config.name} data. [Previous State: {self.state.print} ({self.state.value}), {format_exception(e)}]")

        return result

    async def call(self, code, start, arg):
        _LOGGER.debug(f"[{self.config.serial}] Scheduling request")

        async with asyncio.timeout(TIMINGS_UPDATE_TIMEOUT):
            async with self._semaphore:
                return await self.try_read_write(code, start, arg, f"Call {code:02} ❘ 0x{code:02X} ~ {start} ❘ 0x{start:04X}: {arg}")
