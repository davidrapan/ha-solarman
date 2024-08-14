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
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo, format_mac
from homeassistant.helpers.update_coordinator import UpdateFailed

from .const import *
from .common import *
from .parser import ParameterParser

_LOGGER = logging.getLogger(__name__)

class PySolarmanV5AsyncWrapper(PySolarmanV5Async):
    def __init__(self, address, serial, port, mb_slave_id, passthrough):
        super().__init__(address, serial, port = port, mb_slave_id = mb_slave_id, logger = _LOGGER, auto_reconnect = AUTO_RECONNECT, socket_timeout = TIMINGS_SOCKET_TIMEOUT)
        self._passthrough = passthrough

    async def reconnect(self) -> None:
        """
        Overridden to silence [ConnectionRefusedError: [Errno 111] Connect call failed] during reconnects

        """
        try:
            if self.reader_task:
                self.reader_task.cancel()
            self.reader, self.writer = await asyncio.open_connection(self.address, self.port)
            loop = asyncio.get_running_loop()
            self.reader_task = loop.create_task(self._conn_keeper(), name = "ConnKeeper")
            self.log.debug("[%s] Successful reconnect", self.serial)
            if self.data_wanted_ev.is_set():
                self.log.debug("[%s] Data expected. Will retry the last request", self.serial)
                self.writer.write(self._last_frame)
                await self.writer.drain()
        except Exception as e:
            self.log.debug(f"Cannot open connection to {self.address}. [{type(e).__name__}{f': {e}' if f'{e}' else ''}]")

    def _received_frame_is_valid(self, frame):
        return super()._received_frame_is_valid(frame) if not self._passthrough else True

    def _v5_frame_decoder(self, v5_frame):
        if not self._passthrough:
            return super()._v5_frame_decoder(v5_frame)

        modbus_frame = v5_frame[10:]

        if len(modbus_frame) < 5:
            raise V5FrameError("V5 frame does not contain a valid Modbus RTU frame")

        return modbus_frame

class Inverter(PySolarmanV5AsyncWrapper):
    def __init__(self, address, serial, port, mb_slave_id, passthrough):
        super().__init__(address, serial, port, mb_slave_id, passthrough)
        self._is_reading = 0
        self.state_updated = datetime.now()
        self.state_interval = 0
        self.state = -1
        self.auto_reconnect = AUTO_RECONNECT
        self.manufacturer = "Solarman"
        self.model = None
        self.parameter_definition = None
        self.device_info = {}

    async def load(self, name, mac, path, file):
        self.name = name
        self.mac = mac
        self.lookup_path = path
        self.lookup_file = file if file else "deye_hybrid.yaml"
        self.model = self.lookup_file.replace(".yaml", "")
        self.parameter_definition = await yaml_open(self.lookup_path + self.lookup_file)
        self.profile = ParameterParser(self.parameter_definition)

        if "info" in self.parameter_definition and "model" in self.parameter_definition["info"]:
            info = self.parameter_definition["info"]
            if "manufacturer" in info:
                self.manufacturer = info["manufacturer"]
            if "model" in info:
                self.model = info["model"]
        elif '_' in self.model:
            dev_man = self.model.split('_')
            self.manufacturer = dev_man[0].capitalize()
            self.model = dev_man[1].upper()
        else:
            self.manufacturer = "Solarman"
            self.model = "Stick Logger"

        self.device_info = ({ "connections": {(CONNECTION_NETWORK_MAC, format_mac(self.mac))} } if self.mac else {}) | {
            "identifiers": {(DOMAIN, self.serial)},
            "name": self.name,
            "manufacturer": self.manufacturer,
            "model": self.model,
            "serial_number": self.serial
        }

        _LOGGER.debug(self.device_info)

    def available(self):
        return self.state > -1

    async def async_connect(self, loud = True) -> None:
        if not self.reader_task:
            if loud:
                _LOGGER.info(f"Connecting to {self.address}:{self.port}")
            await self.connect()
        elif not self.state > 0:
            await self.reconnect()

    async def async_disconnect(self, loud = True) -> None:
        if loud:
            _LOGGER.info(f"Disconnecting from {self.address}:{self.port}")
        try:
            await self.disconnect()
        finally:
            self.reader_task = None
            self.reader = None
            self.writer = None

    async def async_shutdown(self, loud = True) -> None:
        self._is_reading = 0
        self.state = -1
        await self.async_disconnect(loud)

    async def async_read(self, params, code, start, end) -> None:
        quantity = end - start + 1

        await self.async_connect()

        match code:
            case 3:
                response = await self.read_holding_registers(start, quantity)
            case 4:
                response = await self.read_input_registers(start, quantity)

        params.parse(response, start, quantity)

    def get_sensors(self):
        return self.profile.get_sensors() if self.parameter_definition else []

    def get_connection_state(self):
        if self.state > 0:
            return "Connected"
        return "Disconnected"

    def get_result(self, middleware = None):
        self._is_reading = 0

        result = middleware.get_result() if middleware else {}

        if len(result) > 0:
            _LOGGER.debug(f"Returning new values to the Coordinator. [Previous State: {self.get_connection_state()} ({self.state})]")
            now = datetime.now()
            self.state_interval = now - self.state_updated
            self.state_updated = now
            self.state = 1

        return result

    async def async_get_failed(self, message = None):
        _LOGGER.debug(f"Request failed. [Previous State: {self.get_connection_state()} ({self.state})]")
        self.state = 0 if self.state == 1 else -1

        await self.async_disconnect()

        if message and self.state == -1:
            raise UpdateFailed(message)

    async def async_get(self, runtime = 0):
        requests = self.profile.get_requests(runtime)
        requests_count = len(requests) if requests else 0
        results = [0] * requests_count

        _LOGGER.debug(f"Scheduling {requests_count} query request{'' if requests_count == 1 else 's'}. #{runtime}")

        self._is_reading = 1

        try:
            async with asyncio.timeout(TIMINGS_UPDATE_TIMEOUT):
                for i, request in enumerate(requests):
                    code = get_request_code(request)
                    start = get_request_start(request)
                    end = get_request_end(request)

                    _LOGGER.debug(f"Querying ({start} - {end}) ...")

                    attempts_left = ACTION_ATTEMPTS
                    while attempts_left > 0 and results[i] == 0:
                        attempts_left -= 1

                        try:
                            await self.async_read(self.profile, code, start, end)
                            results[i] = 1
                        except (V5FrameError, TimeoutError, Exception) as e:
                            results[i] = 0

                            if ((not isinstance(e, TimeoutError) or not attempts_left >= 1) and not (not isinstance(e, TimeoutError) or (e.__cause__ and isinstance(e.__cause__, OSError) and e.__cause__.errno == errno.EHOSTUNREACH))) or _LOGGER.isEnabledFor(logging.DEBUG):
                                _LOGGER.warning(f"Querying ({start} - {end}) failed. #{runtime} [{format_exception(e)}]")

                            await asyncio.sleep((ACTION_ATTEMPTS - attempts_left) * TIMINGS_WAIT_SLEEP)

                        _LOGGER.debug(f"Querying {'succeeded.' if results[i] == 1 else f'attempts left: {attempts_left}{'' if attempts_left > 0 else ', aborting.'}'}")

                    if results[i] == 0:
                        break

                if not 0 in results:
                    return self.get_result(self.profile)
                else:
                    await self.async_get_failed(f"Querying {self.serial} at {self.address}:{self.port} failed.")

        except TimeoutError:
            last_state = self.state
            await self.async_get_failed()
            if last_state < 1:
                raise
            else:
                _LOGGER.debug(f"Timeout fetching {self.name} data")
        except UpdateFailed:
            raise
        except Exception as e:
            await self.async_get_failed(f"Querying {self.serial} at {self.address}:{self.port} failed. [{format_exception(e)}]")

        return self.get_result()

    async def wait_for_reading_done(self, attempts_left = ACTION_ATTEMPTS):
        while self._is_reading == 1 and attempts_left > 0:
            attempts_left -= 1

            await asyncio.sleep(TIMINGS_WAIT_FOR_SLEEP)

        return self._is_reading == 1

    async def service_read_holding_registers(self, register, quantity, wait_for_attempts = ACTION_ATTEMPTS):
        _LOGGER.debug(f"service_read_holding_registers: [{register}], quantity: [{quantity}]")

        if await self.wait_for_reading_done(wait_for_attempts):
            _LOGGER.debug(f"service_read_holding_registers: Timeout.")
            raise TimeoutError("Coordinator is currently reading data from the device!")

        try:
            await self.async_connect()
            return await self.read_holding_registers(register, quantity)
        except Exception as e:
            _LOGGER.warning(f"service_read_holding_registers: [{register}], quantity: [{quantity}] failed. [{format_exception(e)}]")
            if not self.auto_reconnect:
                await self.async_disconnect()

    async def service_read_input_registers(self, register, quantity, wait_for_attempts = ACTION_ATTEMPTS):
        _LOGGER.debug(f"service_read_input_registers: [{register}], quantity: [{quantity}]")

        if await self.wait_for_reading_done(wait_for_attempts):
            _LOGGER.debug(f"service_read_input_registers: Timeout.")
            raise TimeoutError("Coordinator is currently reading data from the device!")

        try:
            await self.async_connect()
            return await self.read_input_registers(register, quantity)
        except Exception as e:
            _LOGGER.warning(f"service_read_input_registers: [{register}], quantity: [{quantity}] failed. [{format_exception(e)}]")
            if not self.auto_reconnect:
                await self.async_disconnect()

    async def service_write_holding_register(self, register, value, wait_for_attempts = ACTION_ATTEMPTS) -> bool:
        _LOGGER.debug(f"service_write_holding_register: {register}, value: {value}")

        if await self.wait_for_reading_done(wait_for_attempts):
            _LOGGER.debug(f"service_write_holding_register: Timeout.")
            raise TimeoutError("Coordinator is currently reading data from the device!")

        attempts_left = ACTION_ATTEMPTS
        while attempts_left > 0:
            attempts_left -= 1

            try:
                await self.async_connect()
                response = await self.write_holding_register(register, value)
                _LOGGER.debug(f"service_write_holding_register: {register}, response: {response}")
                return True
            except Exception as e:
                _LOGGER.warning(f"service_write_holding_register: {register}, value: {value} failed, attempts left: {attempts_left}. [{format_exception(e)}]")
                if not self.auto_reconnect:
                    await self.async_disconnect()
                if not attempts_left > 0:
                    raise

                await asyncio.sleep(TIMINGS_WAIT_SLEEP)

    async def service_write_multiple_holding_registers(self, register, values, wait_for_attempts = ACTION_ATTEMPTS) -> bool:
        _LOGGER.debug(f"service_write_multiple_holding_registers: {register}, values: {values}")

        if await self.wait_for_reading_done(wait_for_attempts):
            _LOGGER.debug(f"service_write_multiple_holding_registers: Timeout.")
            raise TimeoutError("Coordinator is currently reading data from the device!")

        attempts_left = ACTION_ATTEMPTS
        while attempts_left > 0:
            attempts_left -= 1

            try:
                await self.async_connect()
                response = await self.write_multiple_holding_registers(register, values)
                _LOGGER.debug(f"service_write_multiple_holding_registers: {register}, response: {response}")
                return True
            except Exception as e:
                _LOGGER.warning(f"service_write_multiple_holding_registers: {register}, values: {values} failed, attempts left: {attempts_left}. [{format_exception(e)}]")
                if not self.auto_reconnect:
                    await self.async_disconnect()
                if not attempts_left > 0:
                    raise

                await asyncio.sleep(TIMINGS_WAIT_SLEEP)
