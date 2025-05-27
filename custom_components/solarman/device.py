import logging
import asyncio

from datetime import datetime, timedelta

from .const import *
from .common import *
from .provider import *
from .pysolarman.pysolarman import Solarman

_LOGGER = logging.getLogger(__name__)

class DeviceState():
    def __init__(self):
        self.updated: datetime = datetime.now()
        self.updated_interval: timedelta = 0
        self.value: int = -1

    @property
    def print(self):
        return "Connected" if self.value > 0 else "Disconnected"

    def update(self, init: bool = False, exception: Exception | None = None) -> bool:
        now = datetime.now()
        last_value = self.value
        if not init:
            if not exception:
                self.updated, self.updated_interval = now, now - self.updated
                self.value = 1
            else:
                self.value = 0 if self.value == 1 else -1
        else:
            self.updated = now
        if self.value != last_value:
            _LOGGER.debug(f"Device state changed to {self.print}: {self.value}")
        return self.value == -1

class Device():
    def __init__(self, config: ConfigurationProvider):
        self._write_lock: bool = True

        self.state: DeviceState = DeviceState()
        self.config: ConfigurationProvider = config
        self.endpoint: EndPointProvider = None
        self.profile: ProfileProvider = None
        self.modbus: Solarman = None
        self.device_info: dict = {}

    async def setup(self) -> None:
        try:
            self.endpoint = await EndPointProvider(self.config).discover()
            self.profile = ProfileProvider(self.config, self.endpoint)
            self.modbus = Solarman(*self.endpoint.connection)
            await self.profile.resolve(self.get)
        except TimeoutError as e:
            raise TimeoutError(f"Timeout setuping {self.config.name}: {e!r}") from e
        except Exception as e:
            raise Exception(f"Failed setuping {self.config.name}: {e!r}") from e
        finally:
            self.state.update(True)

    def check(self, lock) -> None:
        if lock and self._write_lock:
            raise UserWarning("Entity is locked!")

    async def shutdown(self) -> None:
        self.state.value = -1
        await self.modbus.close()

    async def execute(self, code, address, **kwargs):
        _LOGGER.debug(f"[{self.endpoint.host}] Request {code:02} ❘ 0x{code:02X} ~ {address:04} ❘ 0x{address:04X}: {kwargs}")

        try:
            return await self.modbus.execute(code, address, **kwargs)
        except TimeoutError:
            await self.endpoint.discover(True)
            raise

    @retry()
    async def execute_bulk(self, requests, scheduled):
        responses = {}

        for code, address, _, count in ((get_request_code(request), request[REQUEST_START], request[REQUEST_END], request[REQUEST_COUNT]) for request in scheduled):
            responses[(code, address)] = await self.execute(code, address, count = count)

        return self.profile.parser.process(responses) if requests is None else responses

    async def get(self, runtime = 0, requests = None):
        scheduled, scount, result = *ensure_list_safe_len(self.profile.parser.schedule_requests(runtime) if requests is None else requests), {}

        if scount == 0:
            return result

        _LOGGER.debug(f"[{self.endpoint.host}] Scheduling {scount} query request{'s' if scount != 1 else ''}: {scheduled} #{runtime}")

        try:
            result = await self.execute_bulk(requests, scheduled)
        except Exception as e:
            if self.state.update(exception = e):
                await self.modbus.close()
                self.profile.parser.reset()
                raise
            _LOGGER.debug(f"[{self.endpoint.host}] {"Timeout" if isinstance(e, TimeoutError) else "Error"} fetching {self.config.name} data: {e!r}")

        if (rcount := len(result) if result else 0):
            _LOGGER.debug(f"[{self.endpoint.host}] Returning {rcount} new value{'s' if rcount > 1 else ''}")
            self.state.update()

        return result
