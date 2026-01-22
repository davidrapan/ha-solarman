from __future__ import annotations

from logging import getLogger
from itertools import count
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import *
from .common import *
from .device import Device
from .provider import ConfigurationProvider

_LOGGER = getLogger(__name__)

class Coordinator(DataUpdateCoordinator[dict[str, tuple[int | float | str | list, int | float | None]]]):
    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry[Coordinator]):
        self.device = Device(ConfigurationProvider(hass, config_entry))
        super().__init__(hass, _LOGGER, config_entry = config_entry, name = "", update_interval = TIMINGS_UPDATE_INTERVAL, always_update = False)

    @DataUpdateCoordinator.update_interval.setter
    def update_interval(self, value: timedelta | None):
        DataUpdateCoordinator.update_interval.fset(self, value)
        self.counter = self._update_interval_seconds

    @property
    def name(self):
        return self.device.config.name

    @name.setter
    def name(self, _: str):
        pass

    @property
    def counter(self):
        return self._counter_value

    @counter.setter
    def counter(self, value: int | float):
        self._counter = count(0, int(value))
        self._counter_value = next(self._counter)

    async def _async_setup(self):
        await super()._async_setup()
        try:
            await self.device.setup()
        except TimeoutError:
            raise
        except Exception as e:
            raise UpdateFailed(strepr(e)) from e

    async def _async_update_data(self):
        try:
            return await self.device.get(self.counter)
        except TimeoutError:
            raise
        except Exception as e:
            raise UpdateFailed(strepr(e)) from e

    def _async_refresh_finished(self):
        super()._async_refresh_finished()
        if self.data:
            self._counter_value = next(self._counter)
        elif not self.last_update_success:
            self.counter = self._update_interval_seconds

    async def init(self):
        await super().async_config_entry_first_refresh()
        serial_number, _ = self.data.get(slugify("device", "serial", "number", "sensor"), (str(self.device.modbus.serial) if self.device.modbus.serial > 0 else None, None))
        device_info = build_device_info(self.config_entry.entry_id, serial_number, self.device.endpoint.mac, self.device.endpoint.host, self.device.profile.info, self.device.config.name)
        self.device.info[self.config_entry.entry_id] = device_info
        postprocess_descriptions(self)
        _LOGGER.debug(device_info)
        return self

    async def async_shutdown(self):
        await super().async_shutdown()
        try:
            await self.device.shutdown()
        except Exception as e:
            _LOGGER.exception(f"Unexpected error shutting down {self.name}")
