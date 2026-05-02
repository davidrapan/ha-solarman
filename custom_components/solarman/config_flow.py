from __future__ import annotations

import voluptuous as vol

from typing import Any
from logging import getLogger

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import AbortFlow
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow

from .const import *

_LOGGER = getLogger(__name__)

class ConfigFlowHandler(ConfigFlow):
    VERSION = 2
    domain = DOMAIN

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is None:
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema({
                    vol.Required(CONF_NAME, default="Inverter"): str,
                    vol.Required(CONF_HOST): str,
                    vol.Optional(CONF_PORT, default=8899): int,
                    vol.Optional(CONF_USERNAME, default="admin"): str,
                    vol.Optional(CONF_PASSWORD, default="admin"): str,
                })
            )
        
        return self.async_create_entry(
            title=user_input[CONF_NAME],
            data={},
            options={
                CONF_HOST: user_input[CONF_HOST],
                CONF_PORT: user_input[CONF_PORT],
                CONF_USERNAME: user_input[CONF_USERNAME],
                CONF_PASSWORD: user_input[CONF_PASSWORD],
            }
        )

    @staticmethod
    def async_get_options_flow(entry: ConfigEntry):
        return OptionsFlowHandler(entry)

class OptionsFlowHandler(OptionsFlow):
    def __init__(self, entry: ConfigEntry) -> None:
        self.entry = entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is None:
            return self.async_show_form(
                step_id="init",
                data_schema=vol.Schema({
                    vol.Required(CONF_HOST, default=self.entry.options.get(CONF_HOST, "")): str,
                    vol.Optional(CONF_PORT, default=self.entry.options.get(CONF_PORT, 8899)): int,
                    vol.Optional(CONF_USERNAME, default=self.entry.options.get(CONF_USERNAME, "admin")): str,
                    vol.Optional(CONF_PASSWORD, default=self.entry.options.get(CONF_PASSWORD, "admin")): str,
                })
            )
        
        return self.async_create_entry(data=user_input)
