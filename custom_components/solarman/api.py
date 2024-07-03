import socket
import time
import yaml
import struct
import logging
import asyncio
import aiofiles
import threading
import concurrent.futures

from datetime import datetime
from pysolarmanv5 import PySolarmanV5Async, V5FrameError, NoSocketAvailableError
from homeassistant.helpers.update_coordinator import UpdateFailed

from .const import *
from .common import *
from .parser import ParameterParser

_LOGGER = logging.getLogger(__name__)

def read_file(filepath):
    with open(filepath) as file:
        return file.read()

class InverterApi(PySolarmanV5Async):
    def __init__(self, address, serial, port, mb_slave_id):
        super().__init__(address, serial, port = port, mb_slave_id = mb_slave_id, logger = _LOGGER, auto_reconnect = True, socket_timeout = COORDINATOR_TIMEOUT)
        self._last_frame: bytes = b""
        self.status = -1
        self.status_lastUpdate = "N/A"

    def is_connecting(self):
        return self.status == 0

    def is_connected(self):
        return self.status > -1

    async def reconnect(self) -> None:
        """
        Overridden to prevent the exception to be risen (only logged).
        Because the method is called as a Task.

        """
        try:
            if self.reader_task:
                self.reader_task.cancel()
            self.reader, self.writer = await asyncio.open_connection(self.address, self.port)
            loop = asyncio.get_running_loop()
            self.reader_task = loop.create_task(self._conn_keeper(), name = "ConnKeeper")
            self.log.debug(f"[{self.serial}] Successful reconnect")
            if self.data_wanted_ev.is_set():
                self.log.debug(f"[{self.serial}] Data expected. Will retry the last request")
                self.writer.write(self._last_frame)
                await self.writer.drain()
        except Exception as e:
            self.log.exception(format_exception(e))

    async def _send_receive_v5_frame(self, data_logging_stick_frame):
        """
        Overridden cause of the noisy TimeoutError exception.
        Which is in fact kinda expected cause of communication with Solarman servers to happen now and then.
        
        """
        self.log.debug("[%s] SENT: %s", self.serial, data_logging_stick_frame.hex(" "))
        self.data_wanted_ev.set()
        self._last_frame = data_logging_stick_frame
        try:
            self.writer.write(data_logging_stick_frame)
            await self.writer.drain()
            v5_response = await asyncio.wait_for(self.data_queue.get(), self.socket_timeout)
            if v5_response == b"":
                raise NoSocketAvailableError("Connection closed on read. Retry if auto-reconnect is enabled")
        except AttributeError as exc:
            raise NoSocketAvailableError("Connection already closed") from exc
        except NoSocketAvailableError:
            raise
        except TimeoutError:
            raise
        except Exception as exc:
            self.log.exception("[%s] Send/Receive error: %s", self.serial, exc)
            raise
        finally:
            self.data_wanted_ev.clear()

        self.log.debug("[%s] RECD: %s", self.serial, v5_response.hex(" "))
        return v5_response

    async def async_connect(self) -> None:
        if self.reader_task:
            _LOGGER.debug(f"Reader Task done: {self.reader_task.done()}, cancelled: {self.reader_task.cancelled()}.")
        #if not self.reader_task or self.reader_task.done() or self.reader_task.cancelled():
        if not self.reader_task:
            _LOGGER.info(f"Connecting to {self.address}:{self.port}")
            await self.connect()
        elif not self.is_connected():
            await self.reconnect()

    async def async_disconnect(self, loud = True) -> None:
        if loud:
            _LOGGER.info(f"Disconnecting from {self.address}:{self.port}")

        if self.reader_task:
            self.reader_task.cancel()

        if self.writer:
            try:
                self.writer.write(b"")
                await self.writer.drain()
            except (AttributeError, ConnectionResetError) as e:
                _LOGGER.debug(f"{e} can be during closing ignored.")
            finally:
                self.writer.close()
                await self.writer.wait_closed()

    async def async_reconnect(self) -> None:
        await self.async_disconnect(False)
        loop = asyncio.get_running_loop()
        loop.create_task(self.reconnect())

    async def _read_registers(self, code, params, start, end) -> None:
        length = end - start + 1

        match code:
            case 3:
                response = await self.read_holding_registers(register_addr = start, quantity = length)
            case 4:
                response = await self.read_input_registers(register_addr = start, quantity = length)

        params.parse(response, start, length)

    async def async_read(self, code, params, start, end) -> None:
        await self.async_connect()
        await self._read_registers(code, params, start, end)

class Inverter(InverterApi):
    def __init__(self, address, mac, serial, port, mb_slave_id, lookup_path, lookup_file):
        super().__init__(address, serial, port, mb_slave_id)
        self.mac = mac
        self.lookup_path = lookup_path
        self.lookup_file = lookup_file if lookup_file and not lookup_file == "parameters.yaml" else "deye_hybrid.yaml"

    async def async_load(self):
        loop = asyncio.get_running_loop()
        self.parameter_definition = await loop.run_in_executor(None, lambda: yaml.safe_load(read_file(self.path + self.lookup_file)))

    async def get_sensors(self):
        async with aiofiles.open(self.lookup_path + self.lookup_file) as f:
            self.parameter_definition = await f.read()
        if self.parameter_definition:
            params = ParameterParser(self.parameter_definition)
            return params.get_sensors()
        return []

    def get_connection_status(self):
        if self.is_connected():
            return "Connected"
        return "Disconnected"

    def get_result(self, middleware = None):
        if middleware:
            _LOGGER.debug(f"Querying succeeded, exposing updated values. [Previous Status: {self.get_connection_status()}]")
            self.status_lastUpdate = datetime.now().strftime("%m/%d/%Y, %H:%M:%S")
            self.status = 1

        result = middleware.get_result() if middleware else {}
        result["Connection Status"] = self.get_connection_status()
        return result

    async def async_get_failed(self, message):
        _LOGGER.debug(f"Request failed. [Previous Status: {self.get_connection_status()}]")
        self.status = 0 if self.status == 1 else -1

        await self.async_disconnect()

        if self.status == -1:
            raise UpdateFailed(message)

    async def async_get(self, runtime = 0):
        params = ParameterParser(self.parameter_definition)
        requests = params.get_requests(runtime)
        requests_count = len(requests)
        result = 0

        _LOGGER.debug(f"Scheduling {requests_count} query requests. #{runtime}")

        try:
            for request in requests:
                code = request['mb_functioncode']
                start = request['start']
                end = request['end']

                _LOGGER.debug(f"Querying ({start} - {end}) ...")

                attempts_left = COORDINATOR_QUERY_RETRY_ATTEMPTS
                while attempts_left > 0:
                    attempts_left -= 1

                    try:
                        await self.async_read(code, params, start, end)
                        result = 1
                    except (V5FrameError, TimeoutError, Exception) as e:
                        result = 0

                        if not isinstance(e, TimeoutError) or not attempts_left > 0 or _LOGGER.isEnabledFor(logging.DEBUG):
                            _LOGGER.warning(f"Querying ({start} - {end}) failed. #{runtime} [{format_exception(e)}]")

                        await asyncio.sleep(COORDINATOR_ERROR_SLEEP)

                    _LOGGER.debug(f"Querying {'succeeded.' if result == 1 else f'attempts left: {attempts_left}{'' if attempts_left > 0 else ', aborting.'}'}")

                    if result == 1:
                        break

                if result == 0:
                    break

            if result == 1:
                return self.get_result(params)
            else:
                await self.async_get_failed(f"Querying {self.serial} at {self.address}:{self.port} failed.")

        except UpdateFailed:
            raise
        except Exception as e:
            await self.async_get_failed(f"Querying {self.serial} at {self.address}:{self.port} failed during connection start. [{format_exception(e)}]")

        return self.get_result()

# Service calls
    async def service_write_holding_register(self, register, value):
        _LOGGER.debug(f'Service Call: write_holding_register : [{register}], value : [{value}]')
        try:
            await self.async_connect()
            await self.write_holding_register(register, value)
        except Exception as e:
            _LOGGER.warning(f"Service Call: write_holding_register : [{register}], value : [{value}] failed. [{format_exception(e)}]")
            await self.async_disconnect()
        return

    async def service_write_multiple_holding_registers(self, register, values):
        _LOGGER.debug(f'Service Call: write_multiple_holding_registers: [{register}], values : [{values}]')
        try:
            await self.async_connect()
            await self.write_multiple_holding_registers(register, values)
        except Exception as e:
            _LOGGER.warning(f"Service Call: write_multiple_holding_registers: [{register}], values : [{values}] failed. [{format_exception(e)}]")
            await self.async_disconnect()
        return
