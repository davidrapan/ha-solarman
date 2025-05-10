import logging
import asyncio
import threading
import concurrent.futures

from datetime import datetime

from .const import *
from .common import *
from .provider import *
from .pysolarman.pysolarman import Solarman

_LOGGER = logging.getLogger(__name__)

class DeviceState():
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
            self.updated, self.updated_interval = now, now - self.updated
            self.value = 1

    def reevaluate(self) -> int:
        self.value = 0 if self.value == 1 else -1
        return self.value == -1

class Device():
    def __init__(self, config: ConfigurationProvider):
        self._semaphore = asyncio.Semaphore(1)
        self._write_lock = True

        self.state: DeviceState = DeviceState()
        self.config: ConfigurationProvider = config
        self.endpoint: EndPointProvider = None
        self.profile: ProfileProvider = None
        self.modbus: Solarman = None
        self.device_info: dict = {}

    async def load(self) -> None:
        try:
            self.state.update(True)
            self.endpoint = await EndPointProvider(self.config).discover()
            self.profile = ProfileProvider(self.config, self.endpoint)
            self.modbus = Solarman(*self.endpoint.connection)
            await self.profile.resolve(self.get)
        except TimeoutError as e:
            raise TimeoutError(f"[{self.modbus.address}] Device setup timed out") from e
        except BaseException as e:
            raise Exception(f"[{self.modbus.address}] Device setup failed. [{format_exception(e)}]") from e

    def check(self, lock) -> None:
        if lock and self._write_lock:
            raise UserWarning("Entity is locked!")

    async def shutdown(self) -> None:
        self.state.value = -1
        _LOGGER.info(f"[{self.modbus.address}] Closing connection to {self.endpoint.address}")
        await self.modbus.close()

    async def execute(self, message: str, **kwargs):
        _LOGGER.debug(f"[{self.modbus.address}] {message} ...")

        response = None

        attempts_left = ACTION_ATTEMPTS
        while attempts_left > 0 and response is None:
            attempts_left -= 1
            try:
                response = await self.modbus.execute(**kwargs)

                _LOGGER.debug(f"[{self.modbus.address}] {message} succeeded")
            except Exception as e:
                _LOGGER.debug(f"[{self.modbus.address}] {message} failed, attempts left: {attempts_left}{'' if attempts_left > 0 else ', aborting.'} [{format_exception(e)}]")

                if isinstance(e, TimeoutError):
                    await self.endpoint.discover(True)
                if not attempts_left > 0:
                    raise

        return response

    async def get(self, runtime = 0, requests = None):
        scheduled, scount = ensure_list_safe_len(self.profile.parser.schedule_requests(runtime) if requests is None else requests)
        responses, result = {}, {}

        _LOGGER.debug(f"[{self.modbus.address}] Scheduling {scount} query request{'s' if scount != 1 else ''}. ^{runtime}")

        try:
            if scount == 0:
                await self.modbus.open()
                return result

            async with asyncio.timeout(TIMINGS_UPDATE_TIMEOUT):
                async with self._semaphore:
                    for request in scheduled:
                        code, address, end = get_request_code(request), get_request_start(request), get_request_end(request)
                        count = end - address + 1
                        responses[(code, address)] = await self.execute(f"Querying {code:02} ❘ 0x{code:02X} ~ {address:04} - {end:04} ❘ 0x{address:04X} - 0x{end:04X} #{count:03}", code = code, address = address, count = count)

                    result = self.profile.parser.process(responses) if requests is None else responses

                    if (rcount := len(result) if result else 0) > 0:
                        _LOGGER.debug(f"[{self.modbus.address}] Returning {rcount} new value{'s' if rcount > 1 else ''}. [Previous State: {self.state.print} ({self.state.value})]")
                        self.state.update()

        except Exception as e:
            if self.state.reevaluate():
                _LOGGER.info(f"[{self.modbus.address}] Closing connection")
                await self.modbus.close()
                raise
            _LOGGER.debug(f"[{self.modbus.address}] {"Timeout" if isinstance(e, TimeoutError) else "Error"} fetching {self.config.name} data. [Previous State: {self.state.print} ({self.state.value}), {format_exception(e)}]")

        return result

    async def exe(self, code, address, **kwargs):
        _LOGGER.debug(f"[{self.modbus.address}] Scheduling request")

        async with asyncio.timeout(TIMINGS_UPDATE_TIMEOUT):
            async with self._semaphore:
                return await self.execute(f"Call {code:02} ❘ 0x{code:02X} ~ {address} ❘ 0x{address:04X}: {kwargs}", code = code, address = address, **kwargs)
