from logging import getLogger
from datetime import datetime, timedelta

from .const import *
from .common import *
from .provider import *
from .pysolarman import Solarman

_LOGGER = getLogger(__name__)

class DeviceState():
    def __init__(self):
        self.updated: datetime = datetime.now()
        self.updated_interval: timedelta = 0
        self.value: int = -1

    @property
    def print(self):
        return "Connected" if self.value > 0 else "Disconnected"

    def update(self, init: bool = False, exception: Exception | None = None):
        now = datetime.now()
        if not init:
            if not exception:
                self.updated, self.updated_interval = now, now - self.updated
                self.value = 1
            else:
                self.value = 0 if self.value == 1 else -1
        else:
            self.updated = now
        return self.value == -1

class Device():
    def __init__(self, config: ConfigurationProvider):
        self.config = config

        #self._write_lock = True

        self.endpoint: EndPointProvider | None = None
        self.profile: ProfileProvider | None = None
        self.modbus: Solarman | None = None
        self.state = DeviceState()
        self.info = {}

    async def setup(self):
        try:
            self.endpoint = await EndPointProvider(self.config).init()
            self.modbus = Solarman(*self.endpoint.connection)
            self.profile = await ProfileProvider(self.config, self.endpoint).init(self.get)
        except Exception as e:
            raise type(e)(f"{"Timeout" if (x := isinstance(e, TimeoutError)) else "Error"} setuping {self.config.name}{"" if x else f": {strepr(e)}"}") from e
        else:
            self.state.update(True)

    #def check(self, lock):
    #    if lock and self._write_lock:
    #        raise UserWarning("Entity is locked!")

    async def shutdown(self):
        self.state.value = -1
        if self.modbus:
            await self.modbus.close()

    async def execute(self, code, address, **kwargs):
        _LOGGER.debug(f"[{self.endpoint.host}] Request {code:02} ❘ 0x{code:02X} ~ {address:04} ❘ 0x{address:04X}: {kwargs}")

        try:
            return await self.modbus.execute(code, address, **kwargs)
        except TimeoutError:
            await self.endpoint.discover()
            raise

    @retry(ignore = TimeoutError)
    async def execute_bulk(self, requests, scheduled) -> dict[str | tuple[int, int], tuple[int | float | str | list, int | float | None] | list[int]]:
        responses: dict[tuple[int, int], list[int]] = {}

        for code, address, _, count in ((get_request_code(request), request[REQUEST_START], request[REQUEST_END], request[REQUEST_COUNT]) for request in scheduled):
            responses[(code, address)] = await self.execute(code, address, count = count)

        return self.profile.parser.process(responses) if requests is None else responses

    async def get(self, runtime = 0, requests = None):
        scheduled, scount, result = *ensure_list_safe_len(self.profile.parser.schedule_requests(runtime) if requests is None else requests), {}

        if scount == 0:
            return {None: None}

        _LOGGER.debug(f"[{self.endpoint.host}] Scheduling {scount} query request{'s' if scount != 1 else ''}: {scheduled} #{runtime}")

        try:
            result = await self.execute_bulk(requests, scheduled)
        except ValueError:
            pass
        except Exception as e:
            if self.state.update(exception = e) or runtime == 0:
                await self.modbus.close()
                if self.profile.parser:
                    self.profile.parser.reset()
                raise
            _LOGGER.debug(f"[{self.endpoint.host}] {"Timeout" if (x := isinstance(e, TimeoutError)) else "Error"} fetching {self.config.name} data{"" if x else f": {strepr(e)}"}")

        if (rcount := len(result) if result else 0):
            _LOGGER.debug(f"[{self.endpoint.host}] Returning {rcount} new value{'s' if rcount > 1 else ''}")
            self.state.update()

        return result
