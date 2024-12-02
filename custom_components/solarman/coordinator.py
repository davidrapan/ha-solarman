from __future__ import annotations

import logging

from typing import Any
from collections.abc import Awaitable, Callable

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import *
from .api import Inverter

_LOGGER = logging.getLogger(__name__)

class InverterCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    def __init__(self, hass: HomeAssistant, inverter: Inverter, setup_method: Callable[[], Awaitable[None]] | None = None):
        super().__init__(hass, _LOGGER, name = inverter.name, setup_method = setup_method, update_interval = TIMINGS_UPDATE_INTERVAL, always_update = False)
        self.inverter = inverter
        self._counter = 0

    def _accounting(self) -> int:
        try:
            return int(self._counter * self._update_interval_seconds)
        finally:
            if self.last_update_success:
                self._counter += 1

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            return await self.inverter.get(self._accounting())
        except:
            self._counter = 0
            raise

    #async def _reload(self):
    #    _LOGGER.debug('_reload')
    #    await self.hass.services.async_call("homeassistant", "reload_config_entry", { "entity_id": "???" }, blocking = False)

    async def async_shutdown(self) -> None:
        _LOGGER.debug("async_shutdown")
        await super().async_shutdown()
        await self.inverter.shutdown()