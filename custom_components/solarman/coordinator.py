from __future__ import annotations

import logging

from typing import Any
from itertools import count
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import *
from .common import *
from .device import Device

_LOGGER = logging.getLogger(__name__)

class Coordinator(DataUpdateCoordinator[dict[str, Any]]):
    def __init__(self, hass: HomeAssistant, device: Device):
        self.device: Device = device
        super().__init__(hass, _LOGGER, config_entry = device.config.config_entry, name = device.config.name, update_interval = TIMINGS_UPDATE_INTERVAL, always_update = False)

    @DataUpdateCoordinator.update_interval.setter
    def update_interval(self, value: timedelta | None) -> None:
        DataUpdateCoordinator.update_interval.fset(self, value)
        self.counter = self._update_interval_seconds

    @property
    def counter(self) -> int:
        return self._counter_value

    @counter.setter
    def counter(self, value: int | float) -> None:
        self._counter = count(0, int(value))
        self._counter_value = next(self._counter)

    async def _async_setup(self) -> None:
        await super()._async_setup()
        try:
            await self.device.setup()
        except TimeoutError:
            raise
        except Exception as e:
            raise UpdateFailed(strepr(e)) from e

    async def _async_update_data(self) -> dict[str, Any]:
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
        elif not (self.data and self.last_update_success):
            self.counter = self._update_interval_seconds

    async def async_config_entry_first_refresh(self) -> None:
        await super().async_config_entry_first_refresh()
        device_info = build_device_info(self.config_entry.entry_id, str(self.device.modbus.serial), self.device.endpoint.mac, self.device.endpoint.host, self.device.profile.info, self.device.config.name)
        self.device.device_info[self.config_entry.entry_id] = device_info
        _LOGGER.debug(device_info)

    async def async_shutdown(self) -> None:
        await super().async_shutdown()
        try:
            await self.device.shutdown()
        except Exception as e:
            _LOGGER.exception(f"Unexpected error shutting down {self.name}")
