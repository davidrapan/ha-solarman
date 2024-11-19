from __future__ import annotations

import logging

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import TIMINGS_UPDATE_INTERVAL

_LOGGER = logging.getLogger(__name__)

class InverterCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    def __init__(self, hass: HomeAssistant, inverter) -> None:
        super().__init__(
            hass, 
            _LOGGER, 
            name=inverter.name, 
            update_interval=TIMINGS_UPDATE_INTERVAL, 
            always_update=False
        )
        self.inverter = inverter
        self._counter = 0
        self._last_successful_data: dict[str, Any] = {}
        self._error_logged = False

    def _calculate_accounting(self) -> int:
        try:
            return int(self._counter * (self.update_interval.total_seconds() if self.update_interval else 0))
        finally:
            if self.last_update_success:
                self._counter += 1

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            data = await self.inverter.get(self._calculate_accounting())
            self._last_successful_data = data
            self._error_logged = False
            return data
        except Exception as e:
            if not self._error_logged:
                _LOGGER.warning(f"Failed to update data: {e}")
                self._error_logged = True
            if self._last_successful_data:
                _LOGGER.info("Using last known good data.")
                return self._last_successful_data
            return {}

    async def async_shutdown(self) -> None:
        _LOGGER.debug("Shutting down inverter coordinator.")
        await super().async_shutdown()
        await self.inverter.shutdown()
