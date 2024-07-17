import time
import errno
import struct
import socket
import logging
import asyncio
import threading
import concurrent.futures

from datetime import datetime
from pysolarmanv5 import PySolarmanV5Async, V5FrameError, NoSocketAvailableError
from homeassistant.helpers.update_coordinator import UpdateFailed

from .const import *
from .common import *
from .parser import ParameterParser

_LOGGER = logging.getLogger(__name__)

class InverterApi(PySolarmanV5Async):
    def __init__(self, address, serial, port, mb_slave_id):
        super().__init__(address, serial, port = port, mb_slave_id = mb_slave_id, logger = _LOGGER, auto_reconnect = True, socket_timeout = TIMINGS_SOCKET_TIMEOUT)
        self.status_lastUpdate = "N/A"
        self.status = -1

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
            self.log.exception(f"Cannot open connection to {self.address}. [{format_exception(e)}]")

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
        except AttributeError as e:
            raise NoSocketAvailableError("Connection already closed") from e
        except NoSocketAvailableError:
            raise
        except TimeoutError:
            raise
        except OSError as e:
            if e.errno == errno.EHOSTUNREACH:
                self.log.debug("[%s] EHOSTUNREACH error: %s", self.serial, e)
            self.log.debug("[%s] Send/Receive error: %s", self.serial, e)
            raise TimeoutError()
        except Exception as e:
            self.log.exception("[%s] Send/Receive error: %s", self.serial, e)
            raise
        finally:
            self.data_wanted_ev.clear()

        self.log.debug("[%s] RECD: %s", self.serial, v5_response.hex(" "))
        return v5_response

    async def async_connect(self) -> None:
        if self.reader_task:
            _LOGGER.debug(f"Reader Task done: {self.reader_task.done()}, cancelled: {self.reader_task.cancelled()}.")
        if not self.reader_task: #if not self.reader_task or self.reader_task.done() or self.reader_task.cancelled():
            _LOGGER.info(f"Connecting to {self.address}:{self.port}")
            await self.connect()
        elif not self.status > 0:
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
                try:
                    await self.writer.wait_closed()
                except OSError as e: # Happens when host is unreachable.
                    _LOGGER.debug(f"{e} can be during closing ignored.")

    async def async_read(self, params, code, start, end) -> None:
        length = end - start + 1

        await self.async_connect()

        match code:
            case 3:
                response = await self.read_holding_registers(register_addr = start, quantity = length)
            case 4:
                response = await self.read_input_registers(register_addr = start, quantity = length)

        params.parse(response, start, length)

class Inverter(InverterApi):
    def __init__(self, address, serial, port, mb_slave_id, name, mac, lookup_path, lookup_file):
        super().__init__(address, serial, port, mb_slave_id)
        self.name = name
        self.mac = mac
        self.lookup_path = lookup_path
        self.lookup_file = lookup_file if lookup_file and not lookup_file == "parameters.yaml" else "deye_hybrid.yaml"

        #execute_async(self.load())

    async def load(self):
        self.parameter_definition = await yaml_open(self.lookup_path + self.lookup_file)

    def get_sensors(self):
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

        return middleware.get_result() if middleware else {}

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
                code = get_request_code(request)
                start = get_request_start(request)
                end = get_request_end(request)

                _LOGGER.debug(f"Querying ({start} - {end}) ...")

                attempts_left = ACTION_RETRY_ATTEMPTS
                while attempts_left > 0:
                    attempts_left -= 1

                    try:
                        await self.async_read(params, code, start, end)
                        result = 1
                    except (V5FrameError, TimeoutError, Exception) as e:
                        result = 0

                        if not isinstance(e, TimeoutError) or not attempts_left >= 1 or _LOGGER.isEnabledFor(logging.DEBUG):
                            _LOGGER.warning(f"Querying ({start} - {end}) failed. #{runtime} [{format_exception(e)}]")

                        await asyncio.sleep(TIMINGS_QUERY_EXCEPT_SLEEP)

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
            await self.async_get_failed(f"Querying {self.serial} at {self.address}:{self.port} failed. [{format_exception(e)}]")

        return self.get_result()

    async def service_write_holding_register(self, register, value) -> bool:
        _LOGGER.debug(f"service_write_holding_register: {register}, value: {value}")
        try:
            await self.async_connect()
            response = await self.write_holding_register(register, value)
            _LOGGER.debug(f"service_write_holding_register: {register}, response: {response}")
        except Exception as e:
            _LOGGER.warning(f"service_write_holding_register: {register}, value: {value} failed. [{format_exception(e)}]")
            #await self.async_disconnect()
            raise
        return True

    async def service_write_multiple_holding_registers(self, register, values) -> bool:
        _LOGGER.debug(f"service_write_multiple_holding_registers: {register}, values: {values}")
        try:
            await self.async_connect()
            response = await self.write_multiple_holding_registers(register, values)
            _LOGGER.debug(f"service_write_multiple_holding_register: {register}, response: {response}")
        except Exception as e:
            _LOGGER.warning(f"service_write_multiple_holding_registers: {register}, values: {values} failed. [{format_exception(e)}]")
            #await self.async_disconnect()
            raise
        return True
