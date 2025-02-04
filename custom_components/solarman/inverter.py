import logging
import asyncio
import threading
import concurrent.futures

from datetime import datetime

from .const import *
from .common import *
from .provider import *
from .pysolarman.pysolarman import FUNCTION_CODE, Solarman

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
        self.modbus: Solarman = None
        self.device_info: dict = {}

    async def load(self):
        try:
            self.state.update(True)
            self.endpoint = await EndPointProvider(self.config).discover()
            self.profile = ProfileProvider(self.config, self.endpoint)
            self.modbus = Solarman(*self.endpoint.connection)
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
        _LOGGER.info(f"[{self.config.serial}] Disconnecting from {self.endpoint.address}:{self.endpoint.port}")
        await self.modbus.disconnect()

    async def try_read_write(self, code, start, message: str, **kwargs):
        _LOGGER.debug(f"[{self.config.serial}] {message} ...")

        response = None

        attempts_left = ACTION_ATTEMPTS
        while attempts_left > 0 and response is None:
            attempts_left -= 1
            try:
                response = await self.modbus.execute(code, start, **kwargs)
                #if (response := await self.modbus.execute(code, start, arg)) is not None and (length := ilen(response)) is not None and (expected := arg if code < FUNCTION_CODE.WRITE_SINGLE_COIL else 1) is not None and length != expected:
                #    raise Exception(f"[{self.config.serial}] Unexpected response: Invalid length! (Length: {length}, Expected: {expected})")

                _LOGGER.debug(f"[{self.config.serial}] {message} succeeded, response: {response}")
            except Exception as e:
                _LOGGER.debug(f"[{self.config.serial}] {message} failed, attempts left: {attempts_left}{'' if attempts_left > 0 else ', aborting.'} [{format_exception(e)}]")

                if isinstance(e, TimeoutError):
                    await self.endpoint.discover(True)
                if not attempts_left > 0:
                    raise

        return response

    async def get(self, runtime = 0, requests = None):
        scheduled, scount = ensure_list_safe_len(self.profile.parser.schedule_requests(runtime) if requests is None else requests)
        responses, result = {}, {}

        _LOGGER.debug(f"[{self.config.serial}] Scheduling {scount} query request{'s' if scount != 1 else ''}. ^{runtime}")

        if scount == 0:
            if not self.modbus.connected:
                raise Exception(f"[{self.config.serial}] No scheduled requests found, aborting.")
            return result

        try:
            async with asyncio.timeout(TIMINGS_UPDATE_TIMEOUT):
                async with self._semaphore:
                    for request in scheduled:
                        code, start, end = get_request_code(request), get_request_start(request), get_request_end(request)
                        count = end - start + 1
                        responses[(code, start)] = await self.try_read_write(code, start, f"Querying {code:02} ❘ 0x{code:02X} ~ {start:04} - {end:04} ❘ 0x{start:04X} - 0x{end:04X} #{count:03}", count)

                    result = self.profile.parser.process(responses) if requests is None else responses

                    if (rcount := len(result) if result else 0) > 0:
                        _LOGGER.debug(f"[{self.config.serial}] Returning {rcount} new value{'s' if rcount > 1 else ''}. [Previous State: {self.state.print} ({self.state.value})]")
                        self.state.update()

        except Exception as e:
            if self.state.reevaluate():
                _LOGGER.info(f"[{self.config.serial}] Disconnecting from {self.endpoint.address}:{self.endpoint.port}")
                await self.modbus.disconnect()
                raise
            _LOGGER.debug(f"[{self.config.serial}] {"Timeout" if isinstance(e, TimeoutError) else "Error"} fetching {self.config.name} data. [Previous State: {self.state.print} ({self.state.value}), {format_exception(e)}]")

        return result

    async def call(self, code, start, **kwargs):
        _LOGGER.debug(f"[{self.config.serial}] Scheduling request")

        async with asyncio.timeout(TIMINGS_UPDATE_TIMEOUT):
            async with self._semaphore:
                return await self.try_read_write(code, start, f"Call {code:02} ❘ 0x{code:02X} ~ {start} ❘ 0x{start:04X}: {kwargs}", **kwargs)
