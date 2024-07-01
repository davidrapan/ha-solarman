from __future__ import annotations

import time
import socket
import struct
import logging
import asyncio
import threading
import concurrent.futures

from datetime import datetime
from pysolarmanv5 import PySolarmanV5Async, NoSocketAvailableError

from .const import *
from .common import *

_LOGGER = logging.getLogger(__name__)

class PySolarmanV5AsyncApi(PySolarmanV5Async):
    def __init__(self, address, serial, port, mb_slave_id):
        super().__init__(address, serial, port = port, mb_slave_id = mb_slave_id, logger = _LOGGER, auto_reconnect = True, socket_timeout = COORDINATOR_SOCKET_TIMEOUT)

    async def reconnect(self) -> None:
        """
        Overridden and prevented the exception to be risen (only logged).
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
        Which is in fact kinda expected to happen now and then.
        
        """
        self.log.debug(f"[{self.serial}] SENT: {data_logging_stick_frame.hex(" ")}")
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
        except Exception as e:
            self.log.exception(f"[{self.serial}] Send/Receive error. [{format_exception(e)}]")
            raise
        finally:
            self.data_wanted_ev.clear()

        self.log.debug(f"[{self.serial}] RECD: {v5_response.hex(" ")}")
        return v5_response

class SolarmanApi(PySolarmanV5AsyncApi):
    def __init__(self, address, serial, port, mb_slave_id):
        super().__init__(address, serial, port, mb_slave_id)
        self.status = -1
        self.status_lastUpdate = "N/A"

    async def _async_read_registers(self, code, params, start, end) -> None:
        length = end - start + 1

        match code:
            case 3:
                response = await self.read_holding_registers(register_addr = start, quantity = length)
            case 4:
                response = await self.read_input_registers(register_addr = start, quantity = length)

        params.parse(response, start, length)

    def is_connected(self):
        return self.status > -1

    def set_connection_status(self, status):
        self.status = status
        if self.is_connected():
            self.status_lastUpdate = datetime.now().strftime("%m/%d/%Y, %H:%M:%S")

    def get_connection_status(self):
        if self.is_connected():
            return "Connected"
        return "Disconnected"

    async def async_connect(self) -> None:
        if self.reader_task:
            _LOGGER.debug(f"[{self.serial}] Reader Task done: {self.reader_task.done()}, cancelled: {self.reader_task.cancelled()}.")
        if not self.reader_task: #if not self.reader_task or self.reader_task.done() or self.reader_task.cancelled():
            _LOGGER.info(f"Connecting to {self.address}:{self.port}")
            await self.connect()
        elif not self.is_connected():
            await self.reconnect()

    async def async_disconnect(self, loud = True) -> None:
        if loud:
            _LOGGER.info(f"Disconnecting from {self.address}:{self.port}")

        self.status = 0 if self.status == 1 else -1

        if self.reader_task:
            self.reader_task.cancel()
            try:
                await self.reader_task
            except asyncio.CancelledError:
                _LOGGER.debug(f"Reader Task is cancelled.")

        if self.writer:
            try:
                self.writer.write(b"")
                await self.writer.drain()
            except (AttributeError, ConnectionResetError) as e:
                _LOGGER.debug(f"{e} can be during closing ignored.")
            finally:
                self.writer.close()
                await self.writer.wait_closed()

    async def async_read(self, code, params, start, end) -> None:
        await self.async_connect()
        await self._async_read_registers(code, params, start, end)