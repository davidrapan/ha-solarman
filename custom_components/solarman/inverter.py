from __future__ import annotations

import time
import struct
import socket
import logging
import asyncio
import aiofiles
import threading
import concurrent.futures

from pysolarmanv5 import V5FrameError
from homeassistant.helpers.update_coordinator import UpdateFailed

from .const import *
from .common import *
from .api import SolarmanApi
from .parser import ParameterParser

_LOGGER = logging.getLogger(__name__)

class Inverter(SolarmanApi):
    def __init__(self, address, mac, serial, port, mb_slave_id, lookup_path, lookup_file):
        super().__init__(address, serial, port, mb_slave_id)
        self.mac = mac
        self.lookup_path = lookup_path
        self.lookup_file = lookup_file if lookup_file else DEFAULT_LOOKUP_FILE
        self.parameter_definition = ""

    async def get_sensors(self):
        async with aiofiles.open(self.lookup_path + self.lookup_file) as f:
            self.parameter_definition = await f.read()
        if self.parameter_definition:
            params = ParameterParser(self.parameter_definition)
            return params.get_sensors()
        return []

    def get_result(self, middleware = None):
        if middleware:
            self.set_connection_status(1)
        result = middleware.get_result() if middleware else {}
        result["Connection Status"] = self.get_connection_status()
        return result

    async def async_get_failed(self, message):
        _LOGGER.debug(f"Request failed. [Previous Status: {self.get_connection_status()}]")
        await self.async_disconnect()

        if not self.is_connected():
            raise UpdateFailed(message)

    async def async_get(self, runtime = 0):
        params = ParameterParser(self.parameter_definition)
        requests = params.get_requests(runtime)
        requests_count = len(requests)
        result = 0

        _LOGGER.debug(f"Scheduling {requests_count} query requests. [{runtime}]")

        try:
            for request in requests:
                code = request["mb_functioncode"]
                start = request["start"]
                end = request["end"]

                _LOGGER.debug(f"Querying [{start} - {end}] ...")

                attempts_left = COORDINATOR_QUERY_RETRY_ATTEMPTS #1 if requests_count == 1 else COORDINATOR_QUERY_RETRY_ATTEMPTS

                while attempts_left > 0:
                    attempts_left -= 1

                    try:
                        await self.async_read(code, params, start, end)
                        result = 1
                    except (V5FrameError, TimeoutError, Exception) as e:
                        result = 0

                        if not isinstance(e, TimeoutError) or not attempts_left > 0 or _LOGGER.isEnabledFor(logging.DEBUG):
                            _LOGGER.warning(f"Querying failed. [{format_exception(e)}]")

                        await asyncio.sleep(COORDINATOR_QUERY_ERROR_SLEEP)

                    _LOGGER.debug(f"Querying {'succeeded.' if result == 1 else f'attempts left: {attempts_left}{'' if attempts_left > 0 else ', aborting.'}'}")

                    if result == 1:
                        break

                if result == 0:
                    break

            if result == 1:
                _LOGGER.debug(f"All queries succeeded, exposing updated values. [Previous Status: {self.get_connection_status()}]")
                return self.get_result(params)
            else:
                await self.async_get_failed(f"Querying {self.serial} at {self.address}:{self.port} failed.")

        except UpdateFailed:
            raise
        except Exception as e:
            await self.async_get_failed(f"Querying {self.serial} at {self.address}:{self.port} failed during connection start. [{format_exception(e)}]")

        return self.get_result()

    async def service_write_holding_register(self, register, value):
        _LOGGER.debug(f"Service Call: write_holding_register : [{register}], value : [{value}]")
        try:
            await self.async_connect()
            await self.write_holding_register(register, value)
        except Exception as e:
            _LOGGER.warning(f"Service Call: write_holding_register : [{register}], value : [{value}] failed. [{format_exception(e)}]")
            await self.async_disconnect()
        return

    async def service_write_multiple_holding_registers(self, register, values):
        _LOGGER.debug(f"Service Call: write_multiple_holding_registers: [{register}], values : [{values}]")
        try:
            await self.async_connect()
            await self.write_multiple_holding_registers(register, values)
        except Exception as e:
            _LOGGER.warning(f"Service Call: write_multiple_holding_registers: [{register}], values : [{values}] failed. [{format_exception(e)}]")
            await self.async_disconnect()
        return
