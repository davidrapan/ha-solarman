from unittest.mock import patch, AsyncMock

import pytest
from homeassistant.config_entries import SOURCE_INTEGRATION_DISCOVERY
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.solarman.const import DOMAIN, CONF_HOST

DISCOVERY = {"ip": "192.168.1.60", "mac": "E8:FD:F8:11:22:33", "hostname": "12345", "serial": 12345}


@pytest.fixture(autouse=True)
def mock_deps():
    """Skip HA dependency loading so the missing aiodhcpwatcher package doesn't block tests."""
    with patch("homeassistant.config_entries.async_process_deps_reqs", new=AsyncMock()):
        yield


@pytest.mark.asyncio
async def test_rediscovery_of_known_device_aborts_and_updates_host(hass):
    entry = MockConfigEntry(domain=DOMAIN, title="Inverter", unique_id="e8:fd:f8:11:22:33",
                            options={CONF_HOST: "192.168.1.10"})
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_INTEGRATION_DISCOVERY}, data=DISCOVERY)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured_device"
    assert entry.options[CONF_HOST] == "192.168.1.60"


@pytest.mark.asyncio
async def test_legacy_entry_matched_by_ip_gets_unique_id_backfilled(hass):
    entry = MockConfigEntry(domain=DOMAIN, title="Inverter", unique_id=None,
                            options={CONF_HOST: "192.168.1.60"})
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_INTEGRATION_DISCOVERY}, data=DISCOVERY)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured_device"
    assert entry.unique_id == "e8:fd:f8:11:22:33"
    assert entry.options[CONF_HOST] == "192.168.1.60"


@pytest.mark.asyncio
async def test_unknown_device_shows_user_form_with_unique_id_set(hass):
    async def _empty(*a, **k):
        if False:
            yield
    with patch("custom_components.solarman.config_flow.discover", return_value=_empty()):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_INTEGRATION_DISCOVERY}, data=DISCOVERY)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    flow = next(f for f in hass.config_entries.flow.async_progress() if f["flow_id"] == result["flow_id"])
    assert flow["context"]["unique_id"] == "e8:fd:f8:11:22:33"
